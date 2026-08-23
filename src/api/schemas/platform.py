"""
平台配置 Schema
"""

from typing import Optional
from pydantic import BaseModel, Field


class PlatformBase(BaseModel):
    """平台基础字段"""
    name: str = Field(..., description="平台名称")
    description: Optional[str] = Field(None, description="平台描述")
    icon: Optional[str] = Field(None, description="平台图标URL")
    reach_strategy: str = Field(default="dm", description="默认触达方式: dm/comment_reply")
    status: int = Field(1, description="状态: 0-禁用 1-启用")
    config: Optional[str] = Field(None, description="配置JSON")


class PlatformCreate(PlatformBase):
    """创建平台"""
    code: Optional[str] = Field(None, description="平台代码（不传则自动生成）")


class PlatformUpdate(BaseModel):
    """更新平台"""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    reach_strategy: Optional[str] = None
    status: Optional[int] = None
    config: Optional[str] = None


class PlatformResponse(BaseModel):
    """平台响应"""
    id: int
    code: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    reach_strategy: str = "dm"
    status: int
    config: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
