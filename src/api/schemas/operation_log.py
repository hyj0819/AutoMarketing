"""
操作日志 Schema
"""

from typing import Optional
from pydantic import BaseModel


class OperationLogResponse(BaseModel):
    """操作日志响应"""
    id: int
    operation_type: str
    operator: Optional[str]
    target_type: Optional[str]
    target_id: Optional[int]
    operation_detail: Optional[str]
    ip_address: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class OperationLogListResult(BaseModel):
    """操作日志列表结果"""
    items: list[OperationLogResponse]
    total: int
    page: int
    page_size: int
