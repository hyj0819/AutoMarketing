"""
线索跟进 Schema
"""

from pydantic import BaseModel
from typing import Optional, List, Dict

# 线索生命周期状态
LEAD_STATUSES: Dict[str, str] = {
    'pending': '待触达',
    'contacted': '已私信',
    'replied': '已回复',
    'engaged': '有效对话',
    'qualified': '已确认需求',
    'won': '已成交',
    'lost': '已丢单',
    'invalid': '误判',
    'snoozed': '稍后联系',
}

# 丢单原因（固定枚举，前端必须从中选择）
LOST_REASONS: Dict[str, str] = {
    'price': '价格',
    'no_need': '暂时不需要',
    'bought_other': '已买别家',
    'no_response': '无回应',
    'mistake': '误判',
}


class LeadResponse(BaseModel):
    """线索响应"""
    id: int
    platform_id: int
    platform_name: Optional[str] = None
    business_line_id: int
    business_line_name: Optional[str] = None
    platform_user_id: str
    username: Optional[str] = None
    profile_url: Optional[str] = None
    is_author: int = 0
    contact_status: str
    contact_attempts: int = 0
    last_contact_at: Optional[str] = None
    replied_at: Optional[str] = None
    quote_amount: Optional[float] = None
    quoted_at: Optional[str] = None
    deal_amount: Optional[float] = None
    won_at: Optional[str] = None
    lost_reason: Optional[str] = None
    owner: Optional[str] = None
    snooze_until: Optional[str] = None
    tags: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[str] = None
    # 从 metadata 解析出的证据字段
    comment: Optional[str] = None
    source_title: Optional[str] = None
    source_video: Optional[str] = None
    source_keyword: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LeadStatusUpdate(BaseModel):
    """线索状态流转"""
    to_status: str
    reason: Optional[str] = None
    note: Optional[str] = None
    snooze_until: Optional[str] = None


class LeadQuoteCreate(BaseModel):
    """登记报价"""
    quote_amount: float
    note: Optional[str] = None


class LeadDealCreate(BaseModel):
    """登记成交"""
    deal_amount: float
    product: Optional[str] = None
    note: Optional[str] = None


class LeadBatchRequest(BaseModel):
    """批量操作"""
    ids: List[int]
    action: str  # status | owner | tags
    value: Optional[str] = None
    reason: Optional[str] = None


class LeadBucket(BaseModel):
    """待办分组"""
    key: str
    title: str
    count: int
    list: List[LeadResponse] = []


class LeadTodoStats(BaseModel):
    """待办页顶部数字卡"""
    new_replies: int = 0
    pending_follow: int = 0
    following: int = 0
    won_this_week: int = 0
    won_amount_this_week: float = 0


class LeadTodoResponse(BaseModel):
    """待办页聚合结果"""
    stats: LeadTodoStats
    buckets: List[LeadBucket] = []


class LeadStatusLog(BaseModel):
    """状态流转记录"""
    id: int
    contact_id: int
    from_status: Optional[str] = None
    to_status: str
    reason: Optional[str] = None
    note: Optional[str] = None
    operator: Optional[str] = None
    created_at: Optional[str] = None
