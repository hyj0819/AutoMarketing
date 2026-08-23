"""
任务执行 Schema
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any


# ==================== 创建任务 Schema ====================

class TaskScrapeCreate(BaseModel):
    """创建爬虫任务"""
    task_name: Optional[str] = None
    business_line_id: int
    keywords: List[str] = Field(..., min_items=1, description="关键词列表")
    content_types: List[str] = Field(default=["video", "comment"], description="内容类型: video/comment/post")
    max_items_per_keyword: int = Field(default=50, ge=1, le=500)
    max_comments_per_video: int = Field(default=0, ge=0, le=500, description="每视频评论上限，0=不限制")
    timeout_seconds: int = Field(default=60, ge=10, le=300, description="页面操作超时时间(秒)，默认60秒")
    ai_filter_enabled: bool = True
    ai_prompt_template_id: Optional[int] = None
    exclude_author: bool = True
    account_id: Optional[int] = None

    @field_validator("content_types")
    @classmethod
    def validate_content_types(cls, v):
        valid_types = {"video", "comment"}
        filtered = [t for t in v if t in valid_types]
        if not filtered:
            raise ValueError("内容类型至少需包含 video 或 comment 之一")
        return filtered


class TaskMessageCreate(BaseModel):
    """创建私信任务"""
    task_name: Optional[str] = None
    business_line_id: int
    target_contact_ids: List[int] = Field(..., min_items=1, description="目标用户ID列表")
    message_mode: str = Field(default="personalized", description="消息模式: personalized/fixed")
    fixed_message: Optional[str] = None
    account_id: Optional[int] = None


class TaskReplyCreate(BaseModel):
    """创建评论回复任务"""
    task_name: Optional[str] = None
    business_line_id: int
    keywords: List[str] = Field(..., min_items=1, description="关键词列表")
    prompt_template_id: Optional[int] = None
    max_reply_count: int = Field(default=30, ge=1, le=200)
    account_id: Optional[int] = None


class TaskReachCreate(BaseModel):
    """创建触达任务（合并私信+评论回复，由平台 reach_strategy 决定具体方式）"""
    task_name: Optional[str] = None
    business_line_id: int
    target_contact_ids: List[int] = Field(..., min_items=1, description="目标用户ID列表")
    message_mode: str = Field(default="personalized", description="消息模式: personalized/fixed")
    fixed_message: Optional[str] = None
    account_id: Optional[int] = None
    include_business_info: bool = Field(default=False, description="是否附带商家信息")
    business_info_fields: Optional[List[str]] = Field(
        default=None,
        description="附带商家字段列表: phone/wechat/shop_name/shop_address/site_url",
    )


# ==================== 任务响应 Schema ====================

class TaskExecutionResponse(BaseModel):
    """任务执行响应"""
    id: int
    task_name: Optional[str] = None
    task_type: str
    business_line_id: int
    business_line_name: Optional[str] = None
    platform_name: Optional[str] = None
    status: str
    task_config: Optional[str] = None
    total_items: int
    success_items: int
    failed_items: int
    pending_items: int
    progress: int
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    account_id: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class TaskListResponse(BaseModel):
    """任务列表分页响应"""
    items: List[TaskExecutionResponse]
    total: int
    page: int
    page_size: int


# ==================== 任务日志 Schema ====================

class TaskLogResponse(BaseModel):
    """任务日志响应"""
    id: int
    task_id: int
    log_level: str
    message: str
    created_at: str


class TaskLogListResponse(BaseModel):
    """任务日志列表分页响应"""
    items: List[TaskLogResponse]
    total: int
    page: int
    page_size: int