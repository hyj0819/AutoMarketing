"""任务中心出参模型

字段裁剪：不给 task_config 原文（内含采集深度、超时、AI 模板等执行细节），
只给客户需要判断的进度、计数与失败原因。
"""

from typing import List, Optional

from pydantic import BaseModel


class TaskItem(BaseModel):
    id: int
    task_name: str
    task_type: str
    task_type_label: str = '采集'
    business_line_id: Optional[int] = None
    business_line_name: Optional[str] = None
    platform_name: Optional[str] = None
    status: str
    status_label: str
    progress: int = 0
    total_items: int = 0
    success_items: int = 0
    failed_items: int = 0
    pending_items: int = 0
    hits: int = 0
    created_at: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    queue_position: Optional[int] = None
    eta_minutes: Optional[int] = None
    error_message: Optional[str] = None


class TaskLogItem(BaseModel):
    id: int
    log_level: str
    message: str
    created_at: str


class TaskHitItem(BaseModel):
    id: int
    username: Optional[str] = None
    comment: str = ''
    source_keyword: Optional[str] = None
    ai_level: str = '中'
    status: str
    status_label: str


class TaskDetail(BaseModel):
    task: TaskItem
    logs: List[TaskLogItem]
    hits: List[TaskHitItem]


class TaskCreate(BaseModel):
    business_line_id: int
    task_type: str = 'scrape'
    limit: int = 240
    task_name: Optional[str] = None


class TaskListResult(BaseModel):
    items: List[TaskItem]
    total: int
    page: int
    page_size: int
