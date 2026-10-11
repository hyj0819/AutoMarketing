"""控制台首页出参模型"""

from typing import List, Optional

from pydantic import BaseModel


class QuotaUsage(BaseModel):
    reach_used: int = 0
    reach_limit: int = 0
    ai_used: int = 0
    ai_limit: int = 0
    seats_used: int = 0
    seats_limit: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    days_left: Optional[int] = None
    forecast_exhaust_on: Optional[str] = None


class TodayStats(BaseModel):
    new_leads: int = 0
    sent: int = 0
    replies: int = 0
    won_count: int = 0
    won_amount: float = 0
    reply_rate: float = 0
    delivery_rate: float = 0


class TodoItem(BaseModel):
    kind: str
    title: str
    count: int
    level: str = 'info'


class ActivityItem(BaseModel):
    time: str
    actor: str
    title: str
    detail: Optional[str] = None


class QueueItem(BaseModel):
    id: int
    task_name: str
    status: str
    status_label: str
    progress: int = 0
    processed: int = 0
    total: int = 0
    hits: int = 0
    business_line_name: Optional[str] = None
    queue_position: Optional[int] = None
    eta_minutes: Optional[int] = None
    error_message: Optional[str] = None


class OverviewResult(BaseModel):
    quota: QuotaUsage
    today: TodayStats
    todo: List[TodoItem]
    failed_task_count: int = 0
    activities: List[ActivityItem]
    queue: List[QueueItem]
