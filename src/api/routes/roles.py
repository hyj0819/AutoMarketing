"""
角色管理路由
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.role import CreateRoleRequest, UpdateRoleRequest, RoleResponse, SetRoleMenusRequest
from src.api.routes.auth import get_current_user
from src.api.utils.operation_log import log_operation

router = APIRouter()


@router.get("/", response_model=ApiResponse[dict])
def list_roles(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取角色列表（分页）"""
    sql = "SELECT * FROM roles"
    count_sql = "SELECT COUNT(*) FROM roles"
    conditions = []
    params = {}

    if keyword:
        conditions.append("(role_code LIKE :kw OR role_name LIKE :kw OR description LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status

    if conditions:
        where = " WHERE " + " AND ".join(conditions)
        sql += where
        count_sql += where

    total_cursor = db.execute(text(count_sql), params)
    total = total_cursor.fetchone()[0]

    sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    cursor = db.execute(text(sql), params)
    rows = cursor.fetchall()

    roles = []
    for row in rows:
        # 查询角色的菜单权限
        menus_cursor = db.execute(text(
            "SELECT menu_key FROM role_menus WHERE role_id = :rid"
        ), {"rid": row.id})
        menu_keys = [m.menu_key for m in menus_cursor.fetchall()]

        roles.append({
            "id": row.id,
            "role_code": row.role_code,
            "role_name": row.role_name,
            "description": row.description,
            "status": row.status,
            "created_at": str(row.created_at),
            "updated_at": str(row.updated_at),
            "menu_keys": menu_keys,
        })

    return ApiResponse(result={
        "data": roles,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/all", response_model=ApiResponse[List[dict]])
def list_all_roles(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取所有启用的角色（下拉选择用）"""
    cursor = db.execute(text("SELECT id, role_code, role_name FROM roles WHERE status = 1 ORDER BY role_code"))
    roles = [{"id": r.id, "role_code": r.role_code, "role_name": r.role_name} for r in cursor.fetchall()]
    return ApiResponse(result=roles)


@router.post("/", response_model=ApiResponse[dict])
def create_role(
    data: CreateRoleRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建角色"""
    cursor = db.execute(text("SELECT id FROM roles WHERE role_code = :rc"), {"rc": data.role_code})
    if cursor.fetchone():
        return ApiResponse(code=400, message=f"角色编码 '{data.role_code}' 已存在")

    try:
        cursor = db.execute(text("""
            INSERT INTO roles (role_code, role_name, description)
            VALUES (:rc, :rn, :d)
        """), {"rc": data.role_code, "rn": data.role_name, "d": data.description})
        role_id = cursor.lastrowid
        db.commit()

        client_ip = request.client.host if request.client else None
        log_operation(
            db=db,
            operation_type="创建角色",
            operator=current_user["username"],
            target_type="role",
            target_id=role_id,
            operation_detail=f"创建角色: {data.role_name}({data.role_code})",
            ip_address=client_ip,
        )

        return ApiResponse(result={"id": role_id, "role_code": data.role_code})
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{role_id}", response_model=ApiResponse[dict])
def update_role(
    role_id: int,
    data: UpdateRoleRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新角色"""
    cursor = db.execute(text("SELECT * FROM roles WHERE id = :id"), {"id": role_id})
    role = cursor.fetchone()
    if not role:
        return ApiResponse(code=404, message="角色不存在")

    # 内置角色不允许修改编码
    if role.role_code in ("admin", "operator", "viewer"):
        if data.status is not None and data.status != role.status:
            return ApiResponse(code=400, message="内置角色不允许禁用")

    updates = []
    params = {"id": role_id}

    if data.role_name is not None:
        updates.append("role_name = :role_name")
        params["role_name"] = data.role_name
    if data.description is not None:
        updates.append("description = :description")
        params["description"] = data.description
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE roles SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="编辑角色",
        operator=current_user["username"],
        target_type="role",
        target_id=role_id,
        operation_detail=f"编辑角色ID: {role_id}",
        ip_address=client_ip,
    )

    return ApiResponse(result={"id": role_id})


@router.delete("/{role_id}", response_model=ApiResponse[dict])
def delete_role(
    role_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除角色"""
    cursor = db.execute(text("SELECT * FROM roles WHERE id = :id"), {"id": role_id})
    role = cursor.fetchone()
    if not cursor.fetchone() and not role:
        return ApiResponse(code=404, message="角色不存在")

    # 内置角色不允许删除
    if role.role_code in ("admin", "operator", "viewer"):
        return ApiResponse(code=400, message="内置角色不允许删除")

    # 检查是否有用户关联
    cursor = db.execute(text("SELECT COUNT(*) FROM user_roles WHERE role_id = :rid"), {"rid": role_id})
    count = cursor.fetchone()[0]
    if count > 0:
        return ApiResponse(code=400, message=f"该角色下还有 {count} 个用户，请先移除关联")

    db.execute(text("DELETE FROM role_menus WHERE role_id = :rid"), {"rid": role_id})
    db.execute(text("DELETE FROM roles WHERE id = :id"), {"id": role_id})
    db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="删除角色",
        operator=current_user["username"],
        target_type="role",
        target_id=role_id,
        operation_detail=f"删除角色: {role.role_name}",
        ip_address=client_ip,
    )

    return ApiResponse(result={"message": "角色删除成功"})


@router.get("/{role_id}/menus", response_model=ApiResponse[List[str]])
def get_role_menus(
    role_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取角色的菜单权限"""
    cursor = db.execute(text("SELECT * FROM roles WHERE id = :id"), {"id": role_id})
    if not cursor.fetchone():
        return ApiResponse(code=404, message="角色不存在")

    cursor = db.execute(text("SELECT menu_key FROM role_menus WHERE role_id = :rid"), {"rid": role_id})
    menu_keys = [r.menu_key for r in cursor.fetchall()]
    return ApiResponse(result=menu_keys)


@router.put("/{role_id}/menus", response_model=ApiResponse[dict])
def set_role_menus(
    role_id: int,
    data: SetRoleMenusRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """设置角色的菜单权限"""
    cursor = db.execute(text("SELECT * FROM roles WHERE id = :id"), {"id": role_id})
    if not cursor.fetchone():
        return ApiResponse(code=404, message="角色不存在")

    # 先删后增
    db.execute(text("DELETE FROM role_menus WHERE role_id = :rid"), {"rid": role_id})
    for mk in data.menu_keys:
        db.execute(text("INSERT INTO role_menus (role_id, menu_key) VALUES (:rid, :mk)"), {"rid": role_id, "mk": mk})
    db.commit()

    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="设置角色权限",
        operator=current_user["username"],
        target_type="role",
        target_id=role_id,
        operation_detail=f"设置角色ID: {role_id} 的菜单权限",
        ip_address=client_ip,
    )

    return ApiResponse(result={"message": "菜单权限设置成功"})
