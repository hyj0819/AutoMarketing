"""
门户注册登录路由

/public 下的三个接口不需要登录；/info 与 /logout 需要登录。
注册时要么用邀请码加入已有租户，要么新建一个租户（注册人成为管理员）。
"""

import re
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.auth import (
    AccountInfo,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResult,
    RegisterRequest,
    ResetPasswordRequest,
    TenantBrief,
    TokenResult,
    UserInfoResult,
    menus_for_role,
)
from src.core.database import get_db
from src.core.security import (
    APP_ENV,
    PORTAL_TOKEN_EXPIRE_HOURS,
    create_portal_token,
    create_reset_token,
    decode_reset_token,
)

public_router = APIRouter()
authed_router = APIRouter()

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ---------------- 工具 ----------------

def _validate_email(email: str) -> str:
    email = (email or '').strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail='邮箱格式不正确')
    return email


def _validate_password(password: str) -> None:
    if len(password or '') < 10:
        raise HTTPException(status_code=400, detail='密码至少 10 位')
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise HTTPException(status_code=400, detail='密码需同时包含字母与数字')


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), (password_hash or '').encode())
    except (ValueError, TypeError):
        return False


def _make_tenant_code(email: str, company_name: str = None) -> str:
    """生成租户代号：优先公司名拼音/英文，退化为邮箱域名 + 随机串"""
    base = (company_name or email.split('@')[0] or 'tenant').strip().lower()
    base = re.sub(r'[^a-z0-9]+', '-', base).strip('-') or 'tenant'
    return f"{base[:24]}-{secrets.token_hex(2)}"


def _load_membership(db: Session, account_id: int):
    """加载账号 + 成员 + 租户，取该账号的第一个有效成员关系"""
    return db.execute(
        text("""
            SELECT a.id, a.email, a.real_name, a.last_login_at,
                   m.role, m.visible_scope,
                   t.id AS tenant_id, t.name AS tenant_name, t.plan_code,
                   t.quota_reach, t.quota_ai_calls, t.quota_seats,
                   t.period_start, t.period_end,
                   COALESCE(t.onboarding_done, 0) AS onboarding_done,
                   COALESCE(t.onboarding_step, 1) AS onboarding_step
            FROM portal_accounts a
            JOIN tenant_members m ON m.account_id = a.id AND m.status = 1
            JOIN tenants t ON t.id = m.tenant_id
            WHERE a.id = :aid
            ORDER BY m.id ASC
        """),
        {"aid": account_id},
    ).fetchone()


def _build_result(db: Session, row, token: str) -> LoginResult:
    return LoginResult(
        token=TokenResult(access_token=token, expires_in_hours=PORTAL_TOKEN_EXPIRE_HOURS),
        account=AccountInfo(
            id=row.id,
            email=row.email,
            real_name=row.real_name,
            role=row.role or 'viewer',
            last_login_at=str(row.last_login_at) if row.last_login_at else None,
        ),
        tenant=TenantBrief(
            id=row.tenant_id,
            name=row.tenant_name,
            plan_code=row.plan_code,
            quota_reach=row.quota_reach,
            quota_ai_calls=row.quota_ai_calls,
            quota_seats=row.quota_seats,
            period_start=row.period_start,
            period_end=row.period_end,
            onboarding_done=bool(row.onboarding_done),
            onboarding_step=int(row.onboarding_step or 1),
        ),
        menus=menus_for_role(row.role or 'viewer'),
    )


# ---------------- 公开接口 ----------------

@public_router.post("/register", response_model=ApiResponse[LoginResult])
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """注册：无邀请码则新建租户，有邀请码则加入邀请方租户"""
    email = _validate_email(data.email)
    _validate_password(data.password)

    if db.execute(text("SELECT id FROM portal_accounts WHERE email = :e"), {"e": email}).fetchone():
        raise HTTPException(status_code=400, detail="该邮箱已注册，请直接登录")

    tenant_id = None
    role = 'admin'

    if data.invite_token:
        inv = db.execute(
            text("""
                SELECT id, tenant_id, role, status, expires_at
                FROM tenant_invitations WHERE token = :t
            """),
            {"t": data.invite_token.strip()},
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=400, detail="邀请链接无效")
        if inv.status != 'pending':
            raise HTTPException(status_code=400, detail="邀请链接已被使用")
        if inv.expires_at and str(inv.expires_at) < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
            raise HTTPException(status_code=400, detail="邀请链接已过期")
        tenant_id, role = inv.tenant_id, (inv.role or 'operator')

    if tenant_id is None:
        company_name = (data.company_name or '').strip() or f"{email.split('@')[0]} 的团队"
        cursor = db.execute(
            text("""
                INSERT INTO tenants (code, name, plan_code, status, period_start, period_end)
                VALUES (:code, :name, 'growth', 1, :ps, :pe)
            """),
            {
                "code": _make_tenant_code(email, data.company_name),
                "name": company_name,
                "ps": datetime.now().strftime("%Y-%m-%d"),
                "pe": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
        )
        tenant_id = cursor.lastrowid

    account_cursor = db.execute(
        text("""
            INSERT INTO portal_accounts (email, password_hash, real_name, status, email_verified)
            VALUES (:e, :p, :rn, 1, 0)
        """),
        {"e": email, "p": _hash_password(data.password), "rn": data.real_name or email.split('@')[0]},
    )
    account_id = account_cursor.lastrowid

    db.execute(
        text("""
            INSERT INTO tenant_members (tenant_id, account_id, role, status)
            VALUES (:tid, :aid, :role, 1)
        """),
        {"tid": tenant_id, "aid": account_id, "role": role},
    )

    if data.invite_token:
        db.execute(
            text("UPDATE tenant_invitations SET status = 'accepted' WHERE token = :t"),
            {"t": data.invite_token.strip()},
        )

    db.commit()

    row = _load_membership(db, account_id)
    token = create_portal_token(account_id, row.tenant_id, row.role, row.email)
    return ApiResponse(result=_build_result(db, row, token))


@public_router.post("/login", response_model=ApiResponse[LoginResult])
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """登录：邮箱 + 密码"""
    email = _validate_email(data.email)

    account = db.execute(
        text("SELECT * FROM portal_accounts WHERE email = :e"), {"e": email}
    ).fetchone()
    if not account or not _verify_password(data.password, account.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if account.status != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    row = _load_membership(db, account.id)
    if not row:
        raise HTTPException(status_code=403, detail="账号尚未加入任何租户")

    db.execute(
        text("UPDATE portal_accounts SET last_login_at = :now WHERE id = :id"),
        {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "id": account.id},
    )
    db.commit()

    token = create_portal_token(account.id, row.tenant_id, row.role, row.email)
    return ApiResponse(result=_build_result(db, row, token))


@public_router.post("/password/forgot", response_model=ApiResponse[dict])
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """找回密码：原型没有邮件服务，开发环境直接返回重置令牌便于联调"""
    email = _validate_email(data.email)
    exists = db.execute(
        text("SELECT id FROM portal_accounts WHERE email = :e"), {"e": email}
    ).fetchone()

    result = {"message": "如果该邮箱已注册，重置链接已发送"}
    # 生产环境不回显令牌，避免被枚举
    if exists and APP_ENV not in ('prod', 'production'):
        result["reset_token"] = create_reset_token(email)
        result["expires_in_hours"] = 2
    return ApiResponse(result=result)


@public_router.post("/password/reset", response_model=ApiResponse[dict])
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """用重置令牌设置新密码"""
    email = decode_reset_token(data.token)
    if not email or email != _validate_email(data.email):
        raise HTTPException(status_code=400, detail="重置链接无效或已过期")
    _validate_password(data.password)

    account = db.execute(
        text("SELECT id FROM portal_accounts WHERE email = :e"), {"e": email}
    ).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    db.execute(
        text("UPDATE portal_accounts SET password_hash = :p, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"p": _hash_password(data.password), "id": account.id},
    )
    db.commit()
    return ApiResponse(result={"message": "密码已重置，请重新登录"})


# ---------------- 需登录接口 ----------------

@authed_router.get("/info", response_model=ApiResponse[UserInfoResult])
def get_info(ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """当前登录用户、所属租户与可见菜单"""
    row = _load_membership(db, ctx.account_id)
    if not row:
        raise HTTPException(status_code=401, detail="账号尚未加入任何租户")
    return ApiResponse(result=UserInfoResult(
        account=AccountInfo(
            id=row.id,
            email=row.email,
            real_name=row.real_name,
            role=row.role or 'viewer',
            last_login_at=str(row.last_login_at) if row.last_login_at else None,
        ),
        tenant=TenantBrief(
            id=row.tenant_id,
            name=row.tenant_name,
            plan_code=row.plan_code,
            quota_reach=row.quota_reach,
            quota_ai_calls=row.quota_ai_calls,
            quota_seats=row.quota_seats,
            period_start=row.period_start,
            period_end=row.period_end,
            onboarding_done=bool(row.onboarding_done),
            onboarding_step=int(row.onboarding_step or 1),
        ),
        menus=menus_for_role(row.role or 'viewer'),
    ))


@authed_router.post("/logout", response_model=ApiResponse[dict])
def logout(ctx: TenantContext = Depends(get_portal_user)):
    """退出登录：令牌无状态，前端清理本地令牌即可"""
    return ApiResponse(result={"message": "已退出登录"})
