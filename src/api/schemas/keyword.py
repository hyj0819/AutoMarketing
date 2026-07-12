"""
关键词配置 Schema
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class KeywordBase(BaseModel):
    """关键词基础字段"""
    keyword: str = Field(..., description="关键词")
    priority: int = Field(0, description="优先级")
    status: int = Field(1, description="状态: 0-禁用 1-启用")


class KeywordCreate(KeywordBase):
    """创建关键词"""
    business_line_id: int = Field(..., description="业务线ID")


class KeywordBatchCreate(BaseModel):
    """批量创建关键词"""
    business_line_id: int = Field(..., description="业务线ID")
    keywords: List[str] = Field(..., description="关键词列表")
    priority: int = Field(0, description="优先级")
    status: int = Field(1, description="状态: 0-禁用 1-启用")


class KeywordUpdate(BaseModel):
    """更新关键词"""
    keyword: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[int] = None


class KeywordResponse(BaseModel):
    """关键词响应"""
    id: int
    business_line_id: int
    business_line_name: Optional[str] = None
    keyword: str
    priority: int
    status: int
    created_at: str

    class Config:
        from_attributes = True
