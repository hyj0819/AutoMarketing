"""
任务执行 Schema
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ==================== 创建任务 Schema ====================

class TaskScrapeCreate(BaseModel):
    """创建爬虫任务"""
    task_name: Optional[str] = None
    business_line_id: int
    keywords: List[str] = Field(..., min_items=1, description="关键词列表")
    content_types: List[str] = Field(default=["video", "comment"], description="内容类型: video/comment/post")
    max_items_per_keyword: int = Field(default=50, ge=1, le=500)
    ai_filter_enabled: bool = True
    ai_prompt_template_id: Optional[int] = None
    exclude_author: bool = True
    account_id: Optional[int] = None


class TaskMessageCreate(BaseModel):
    """创建私信任务"""
    task_name: Optional[str] = None
    business_line_id: int
    target_contact_ids: List[int] = Field(..., min_items=1, description="目标用户ID列表")
    message_mode: str = Field(default="personalized", description="消息模式: personalized/fixed")
    prompt_template_id: Optional[int] = None
    fixed_message: Optional[str] = None
    max_send_count: int = Field(default=50, ge=1, le=500)
    send_interval_min: int = Field(default=8, ge=1, description="发送最小间隔(分钟)")
    send_interval_max: int = Field(default=20, ge=1, description="发送最大间隔(分钟)")
    account_id: Optional[int] = None


class TaskReplyCreate(BaseModel):
    """创建评论回复任务"""
    task_name: Optional[str] = None
    business_line_id: int
    keywords: List[str] = Field(..., min_items=1, description="关键词列表")
    prompt_template_id: Optional[int] = None
    max_reply_count: int = Field(default=30, ge=1, le=200)
    account_id: Optional[int] = None


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