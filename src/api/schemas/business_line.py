"""
业务线配置 Schema
"""

from typing import Optional
from pydantic import BaseModel, Field


class BusinessLineBase(BaseModel):
    """业务线基础字段"""
    code: str = Field(..., description="业务线代码")
    name: str = Field(..., description="业务线名称")
    status: int = Field(1, description="状态: 0-禁用 1-启用")
    config: Optional[str] = Field(None, description="配置JSON")


class BusinessLineCreate(BusinessLineBase):
    """创建业务线"""
    platform_id: int = Field(..., description="平台ID")


class BusinessLineUpdate(BaseModel):
    """更新业务线"""
    name: Optional[str] = None
    status: Optional[int] = None
    config: Optional[str] = None


class BusinessLineResponse(BaseModel):
    """业务线响应"""
    id: int
    platform_id: int
    platform_name: Optional[str] = None
    code: str
    name: str
    status: int
    config: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
