"""
内容数据 Schema
"""

from pydantic import BaseModel
from typing import Optional


class ContentCreate(BaseModel):
    """创建内容数据"""
    platform_id: int
    business_line_id: int
    content_type: str
    content_id: str
    content_url: str
    title: Optional[str] = None
    content_text: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    engagement_stats: Optional[str] = None
    ai_analysis_result: Optional[str] = None
    source_keyword: Optional[str] = None


class ContentUpdate(BaseModel):
    """更新内容数据"""
    title: Optional[str] = None
    content_text: Optional[str] = None
    engagement_stats: Optional[str] = None
    ai_analysis_result: Optional[str] = None


class ContentResponse(BaseModel):
    """内容数据响应"""
    id: int
    platform_id: int
    platform_name: Optional[str] = None
    business_line_id: int
    business_line_name: Optional[str] = None
    content_type: str
    content_id: str
    content_url: str
    title: Optional[str]
    content_text: Optional[str]
    author_id: Optional[str]
    author_name: Optional[str]
    engagement_stats: Optional[str]
    ai_analysis_result: Optional[str]
    source_keyword: Optional[str]
    scraped_at: str
