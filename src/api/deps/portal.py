"""
门户（客户控制台）鉴权与租户上下文

设计要点：
1. tenant_id 只从令牌里取，绝不信任前端参数，避免越权访问其他租户数据
2. 门户令牌 kind='portal'，与自用端的内部令牌互不通用
3. 门户路由统一用 APIRouter(dependencies=[...]) 挂载，不留裸奔接口
"""

from typing import Callable, List, Literal, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import decode_portal_token


class TenantContext(BaseModel):
    """租户上下文：一次请求里唯一的身份与隔离边界"""

    tenant_id: int
    account_id: int
    role: Literal['admin', 'operator', 'viewer']
    email: str
    real_name: Optional[str] = None
    visible_scope: Optional[List[int]] = None

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'

    @property
    def can_write(self) -> bool:
        return self.role in ('admin', 'operator')


def get_portal_user(request: Request, db: Session = Depends(get_db)) -> TenantContext:
    """解析门户令牌并校验账号、成员与租户状态"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    payload = decode_portal_token(auth_header[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    try:
        account_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    row = db.execute(
        text("""
            SELECT a.id, a.email, a.real_name, a.status AS account_status,
                   m.role, m.status AS member_status, m.visible_scope,
                   t.id AS tenant_id, t.status AS tenant_status
            FROM portal_accounts a
            JOIN tenant_members m ON m.account_id = a.id AND m.status = 1
            JOIN tenants t ON t.id = m.tenant_id
            WHERE a.id = :aid
            ORDER BY m.id ASC
        """),
        {"aid": account_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="账号不存在或已被移出租户")
    if row.account_status != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    if row.tenant_status != 1:
        raise HTTPException(status_code=403, detail="租户已停用，请联系平台")

    return TenantContext(
        tenant_id=row.tenant_id,
        account_id=row.id,
        role=row.role or 'viewer',
        email=row.email,
        real_name=row.real_name,
        visible_scope=_parse_scope(row.visible_scope),
    )


def _parse_scope(raw: Optional[str]) -> Optional[List[int]]:
    """visible_scope 存 JSON 数组，为空表示可见全部项目"""
    if not raw:
        return None
    import json

    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(value, list) and value:
        return [int(x) for x in value if str(x).isdigit()]
    return None


def require_role(*roles: str) -> Callable:
    """角色守卫：只读角色不能调写入口"""

    def _dep(ctx: TenantContext = Depends(get_portal_user)) -> TenantContext:
        if ctx.role not in roles:
            raise HTTPException(status_code=403, detail="当前角色没有该操作权限")
        return ctx

    return _dep
