"""
认证路由 - 登录/登出/获取用户信息
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import bcrypt
from jose import jwt, JWTError
import os

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.user import LoginRequest, LoginResponse, UserInfo

router = APIRouter()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "automarketing-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_access_token(user_id: int, username: str) -> str:
    """创建 JWT Token"""
    from datetime import timedelta
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    """从 Token 中解析当前用户信息"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或 Token 已过期")
    
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="未登录或 Token 已过期")
    
    # 查询用户
    cursor = db.execute(text("SELECT * FROM users WHERE id = :id AND status = 1"), {"id": user_id})
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    
    return {"id": user.id, "username": user.username}


@router.post("/login", response_model=ApiResponse[dict])
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    # 查询用户
    cursor = db.execute(
        text("SELECT * FROM users WHERE username = :username"),
        {"username": data.username}
    )
    user = cursor.fetchone()
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if user.status != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    
    # 验证密码
    if not bcrypt.checkpw(data.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 生成 Token
    access_token = create_access_token(user.id, user.username)
    
    # 更新最后登录时间
    db.execute(
        text("UPDATE users SET last_login_at = :now WHERE id = :id"),
        {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "id": user.id}
    )
    db.commit()
    
    # 查询用户角色和菜单权限
    roles = _get_user_roles(db, user.id)
    menus = _get_user_menus(db, user.id)
    
    # 记录操作日志
    client_ip = request.client.host if request.client else None
    from src.api.utils.operation_log import log_operation
    log_operation(
        db=db,
        operation_type="用户登录",
        operator=user.username,
        target_type="user",
        target_id=user.id,
        operation_detail=f"用户 {user.username} 登录",
        ip_address=client_ip,
    )
    
    return ApiResponse(result={
        "access_token": access_token,
        "token_type": "Bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "email": user.email,
            "roles": roles,
            "menus": menus,
        }
    })


@router.get("/info", response_model=ApiResponse[UserInfo])
def get_user_info(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前登录用户信息"""
    cursor = db.execute(
        text("SELECT * FROM users WHERE id = :id"),
        {"id": current_user["id"]}
    )
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    roles = _get_user_roles(db, user.id)
    menus = _get_user_menus(db, user.id)
    
    return ApiResponse(result=UserInfo(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        email=user.email,
        status=user.status,
        last_login_at=str(user.last_login_at) if user.last_login_at else None,
        created_at=str(user.created_at),
        updated_at=str(user.updated_at),
        roles=roles,
        menus=menus,
    ))


def _get_user_roles(db: Session, user_id: int) -> list:
    """获取用户的角色列表"""
    cursor = db.execute(text("""
        SELECT r.id, r.role_code, r.role_name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = :uid AND r.status = 1
    """), {"uid": user_id})
    return [{"id": r.id, "role_code": r.role_code, "role_name": r.role_name} for r in cursor.fetchall()]


def _get_user_menus(db: Session, user_id: int) -> list:
    """获取用户的菜单权限列表（合并所有角色的菜单）"""
    cursor = db.execute(text("""
        SELECT DISTINCT rm.menu_key
        FROM user_roles ur
        JOIN role_menus rm ON ur.role_id = rm.role_id
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = :uid AND r.status = 1
    """), {"uid": user_id})
    return [r.menu_key for r in cursor.fetchall()]
