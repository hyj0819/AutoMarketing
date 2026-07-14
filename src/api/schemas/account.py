"""
账号配置 Schema
"""

from typing import Optional
from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    """创建账号"""
    account_name: str = Field(..., description="账号名称")
    platform_id: int = Field(..., description="所属平台ID")
    browser_id: Optional[str] = Field(None, description="指纹浏览器用户ID")
    notes: Optional[str] = Field(None, description="备注")


class AccountUpdate(BaseModel):
    """更新账号"""
    account_name: Optional[str] = None
    platform_id: Optional[int] = None
    browser_id: Optional[str] = None
    status: Optional[int] = Field(None, description="状态: 0-禁用 1-启用")
    notes: Optional[str] = None


class AccountResponse(BaseModel):
    """账号响应"""
    id: int
    account_name: str
    platform_id: int
    platform_name: Optional[str] = None
    browser_id: Optional[str]
    status: int
    notes: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
