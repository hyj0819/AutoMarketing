"""线索池出参模型"""

from typing import List, Optional

from pydantic import BaseModel


class LeadItem(BaseModel):
    id: int
    username: Optional[str] = None
    platform_name: Optional[str] = None
    business_line_name: Optional[str] = None
    comment: str = ''
    source_keyword: Optional[str] = None
    ai_level: str = '中'
    status: str
    status_label: str
    owner: Optional[str] = None
    quote_amount: Optional[float] = None
    deal_amount: Optional[float] = None
    lost_reason: Optional[str] = None
    last_contact_at: Optional[str] = None
    created_at: str


class LeadEvidence(BaseModel):
    comment: str = ''
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    ai_conclusion: str = ''
    hit_reason: str = ''


class TimelineItem(BaseModel):
    time: str
    title: str
    actor: str = '系统'
    detail: Optional[str] = None


class LeadDetail(BaseModel):
    lead: LeadItem
    evidence: LeadEvidence
    context: dict
    timeline: List[TimelineItem]


class LeadStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None
    note: Optional[str] = None


class LeadListResult(BaseModel):
    items: List[LeadItem]
    total: int
    page: int
    page_size: int
