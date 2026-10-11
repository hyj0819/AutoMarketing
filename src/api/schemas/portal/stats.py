"""数据看板出参模型"""

from typing import List, Optional

from pydantic import BaseModel


class FunnelStage(BaseModel):
    key: str
    title: str
    count: int
    rate: Optional[float] = None  # 相对上一级的转化率


class FunnelResult(BaseModel):
    stages: List[FunnelStage]
    won_amount: float = 0
    avg_deal_amount: float = 0
    won_count: int = 0
    lost_count: int = 0
    lost_reasons: List[dict] = []


class TrendPoint(BaseModel):
    label: str
    leads: int = 0
    reach: int = 0


class TrendResult(BaseModel):
    granularity: str
    points: List[TrendPoint]


class AttributionItem(BaseModel):
    keyword: str
    leads: int = 0
    replies: int = 0
    won: int = 0
    amount: float = 0


class ScriptEffectItem(BaseModel):
    name: str
    reach: int = 0
    replies: int = 0
    reply_rate: float = 0
    is_active: int = 0
