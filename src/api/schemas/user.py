"""
用户管理 Schema
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "Bearer"


class UserInfo(BaseModel):
    """用户信息"""
    id: int
    username: str
    real_name: Optional[str] = None
    email: Optional[str] = None
    status: int
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: str
    roles: Optional[List[dict]] = None
    menus: Optional[List[str]] = None


class CreateUserRequest(BaseModel):
    """创建用户"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")
    real_name: Optional[str] = Field(None, max_length=50, description="真实姓名")
    email: Optional[str] = Field(None, max_length=100, description="邮箱")
    role_ids: Optional[List[int]] = Field(None, description="角色ID列表")


class UpdateUserRequest(BaseModel):
    """更新用户"""
    real_name: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    status: Optional[int] = Field(None, description="状态: 0-禁用 1-启用")
    role_ids: Optional[List[int]] = None


class ResetPasswordRequest(BaseModel):
    """重置密码"""
    new_password: str = Field(..., min_length=6, max_length=50, description="新密码")


class AssignRolesRequest(BaseModel):
    """分配角色"""
    role_ids: List[int] = Field(..., description="角色ID列表")
