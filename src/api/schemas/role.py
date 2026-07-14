"""
角色管理 Schema
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class CreateRoleRequest(BaseModel):
    """创建角色"""
    role_code: str = Field(..., min_length=2, max_length=50, description="角色编码")
    role_name: str = Field(..., min_length=2, max_length=50, description="角色名称")
    description: Optional[str] = Field(None, max_length=200, description="描述")


class UpdateRoleRequest(BaseModel):
    """更新角色"""
    role_name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=200)
    status: Optional[int] = Field(None, description="状态: 0-禁用 1-启用")


class RoleResponse(BaseModel):
    """角色响应"""
    id: int
    role_code: str
    role_name: str
    description: Optional[str] = None
    status: int
    created_at: str
    updated_at: str
    menu_keys: Optional[List[str]] = None

    class Config:
        from_attributes = True


class SetRoleMenusRequest(BaseModel):
    """设置角色菜单权限"""
    menu_keys: List[str] = Field(..., description="菜单 key 列表")
