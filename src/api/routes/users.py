"""
用户管理路由
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
import bcrypt

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.user import CreateUserRequest, UpdateUserRequest, ResetPasswordRequest, AssignRolesRequest
from src.api.routes.auth import get_current_user
from src.api.utils.operation_log import log_operation

router = APIRouter()


@router.get("/", response_model=ApiResponse[dict])
def list_users(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[int] = None,
    role_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户列表（分页）"""
    sql = """
        SELECT u.id, u.username, u.real_name, u.email, u.status,
               u.last_login_at, u.created_at, u.updated_at
        FROM users u
    """
    count_sql = "SELECT COUNT(*) FROM users u"
    conditions = []
    params = {}

    if keyword:
        conditions.append("(u.username LIKE :kw OR u.real_name LIKE :kw OR u.email LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if status is not None:
        conditions.append("u.status = :status")
        params["status"] = status
    if role_id is not None:
        sql += " JOIN user_roles ur_filter ON u.id = ur_filter.user_id"
        count_sql += " JOIN user_roles ur_filter ON u.id = ur_filter.user_id"
        conditions.append("ur_filter.role_id = :role_id")
        params["role_id"] = role_id

    if conditions:
        where = " WHERE " + " AND ".join(conditions)
        sql += where
        count_sql += where

    # 总数
    total_cursor = db.execute(text(count_sql), params)
    total = total_cursor.fetchone()[0]

    # 分页
    sql += " ORDER BY u.created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    cursor = db.execute(text(sql), params)
    rows = cursor.fetchall()

    users = []
    for row in rows:
        # 查询每个用户的角色
        roles_cursor = db.execute(text("""
            SELECT r.id, r.role_code, r.role_name
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = :uid
        """), {"uid": row.id})
        roles = [{"id": r.id, "role_code": r.role_code, "role_name": r.role_name} for r in roles_cursor.fetchall()]

        users.append({
            "id": row.id,
            "username": row.username,
            "real_name": row.real_name,
            "email": row.email,
            "status": row.status,
            "last_login_at": str(row.last_login_at) if row.last_login_at else None,
            "created_at": str(row.created_at),
            "updated_at": str(row.updated_at),
            "roles": roles,
        })

    return ApiResponse(result={
        "data": users,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/", response_model=ApiResponse[dict])
def create_user(
    data: CreateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建用户"""
    # 检查用户名是否已存在
    cursor = db.execute(text("SELECT id FROM users WHERE username = :u"), {"u": data.username})
    if cursor.fetchone():
        return ApiResponse(code=400, message=f"用户名 '{data.username}' 已存在")

    pwd_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    try:
        cursor = db.execute(text("""
            INSERT INTO users (username, password_hash, real_name, email, status)
            VALUES (:u, :p, :rn, :e, 1)
        """), {
            "u": data.username,
            "p": pwd_hash,
            "rn": data.real_name,
            "e": data.email,
        })
        user_id = cursor.lastrowid

        # 分配角色
        if data.role_ids:
            for rid in data.role_ids:
                db.execute(text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"), {"uid": user_id, "rid": rid})

        db.commit()

        client_ip = request.client.host if request.client else None
        log_operation(
            db=db,
            operation_type="创建用户",
            operator=current_user["username"],
            target_type="user",
            target_id=user_id,
            operation_detail=f"创建用户: {data.username}",
            ip_address=client_ip,
        )

        return ApiResponse(result={"id": user_id, "username": data.username})
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{user_id}", response_model=ApiResponse[dict])
def update_user(
    user_id: int,
    data: UpdateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新用户"""
    cursor = db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
    if not cursor.fetchone():
        return ApiResponse(code=404, message="用户不存在")

    updates = []
    params = {"id": user_id}

    if data.real_name is not None:
        updates.append("real_name = :real_name")
        params["real_name"] = data.real_name
    if data.email is not None:
        updates.append("email = :email")
        params["email"] = data.email
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE users SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)

    # 更新角色
    if data.role_ids is not None:
        db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
        for rid in data.role_ids:
            db.execute(text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"), {"uid": user_id, "rid": rid})

    db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="编辑用户",
        operator=current_user["username"],
        target_type="user",
        target_id=user_id,
        operation_detail=f"编辑用户ID: {user_id}",
        ip_address=client_ip,
    )

    return ApiResponse(result={"id": user_id})


@router.post("/{user_id}/reset-password", response_model=ApiResponse[dict])
def reset_password(
    user_id: int,
    data: ResetPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重置用户密码"""
    cursor = db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
    if not cursor.fetchone():
        return ApiResponse(code=404, message="用户不存在")

    pwd_hash = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
    db.execute(text("UPDATE users SET password_hash = :p, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
               {"p": pwd_hash, "id": user_id})
    db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="重置密码",
        operator=current_user["username"],
        target_type="user",
        target_id=user_id,
        operation_detail=f"重置用户ID: {user_id} 的密码",
        ip_address=client_ip,
    )

    return ApiResponse(result={"message": "密码重置成功"})


@router.put("/{user_id}/status", response_model=ApiResponse[dict])
def update_user_status(
    user_id: int,
    status: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """启用/禁用用户"""
    cursor = db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
    user = cursor.fetchone()
    if not user:
        return ApiResponse(code=404, message="用户不存在")

    if user.username == "admin":
        return ApiResponse(code=400, message="不能禁用超级管理员账号")

    db.execute(text("UPDATE users SET status = :s, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
               {"s": status, "id": user_id})
    db.commit()

    status_text = "启用" if status == 1 else "禁用"
    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type=f"{status_text}用户",
        operator=current_user["username"],
        target_type="user",
        target_id=user_id,
        operation_detail=f"{status_text}用户ID: {user_id}",
        ip_address=client_ip,
    )

    return ApiResponse(result={"message": f"用户已{status_text}"})


@router.delete("/{user_id}", response_model=ApiResponse[dict])
def delete_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除用户"""
    cursor = db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
    user = cursor.fetchone()
    if not user:
        return ApiResponse(code=404, message="用户不存在")

    if user.username == "admin":
        return ApiResponse(code=400, message="不能删除超级管理员账号")

    db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="删除用户",
        operator=current_user["username"],
        target_type="user",
        target_id=user_id,
        operation_detail=f"删除用户: {user.username}",
        ip_address=client_ip,
    )

    return ApiResponse(result={"message": "用户删除成功"})


@router.post("/{user_id}/roles", response_model=ApiResponse[dict])
def assign_roles(
    user_id: int,
    data: AssignRolesRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分配用户角色"""
    cursor = db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
    if not cursor.fetchone():
        return ApiResponse(code=404, message="用户不存在")

    db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
    for rid in data.role_ids:
        db.execute(text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"), {"uid": user_id, "rid": rid})
    db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="分配角色",
        operator=current_user["username"],
        target_type="user",
        target_id=user_id,
        operation_detail=f"为用户ID: {user_id} 分配角色: {data.role_ids}",
        ip_address=client_ip,
    )

    return ApiResponse(result={"message": "角色分配成功"})
