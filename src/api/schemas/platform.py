"""
平台配置 Schema
"""

from typing import Optional
from pydantic import BaseModel, Field


class PlatformBase(BaseModel):
    """平台基础字段"""
    code: str = Field(..., description="平台代码")
    name: str = Field(..., description="平台名称")
    status: int = Field(1, description="状态: 0-禁用 1-启用")
    config: Optional[str] = Field(None, description="配置JSON")


class PlatformCreate(PlatformBase):
    """创建平台"""
    pass


class PlatformUpdate(BaseModel):
    """更新平台"""
    name: Optional[str] = None
    status: Optional[int] = None
    config: Optional[str] = None


class PlatformResponse(BaseModel):
    """平台响应"""
    id: int
    code: str
    name: str
    status: int
    config: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
