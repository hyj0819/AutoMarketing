"""
通用响应模型
"""

from typing import Generic, TypeVar, Optional, List
from pydantic import BaseModel

T = TypeVar('T')


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    code: int = 200
    message: str = "success"
    result: Optional[T] = None


class PageResult(BaseModel, Generic[T]):
    """分页数据"""
    data: List[T]
    total: int
    page: int
    page_size: int
    pages: int


class PageParams(BaseModel):
    """分页参数"""
    page: int = 1
    page_size: int = 20
