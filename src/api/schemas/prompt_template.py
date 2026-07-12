"""
提示词模板 Schema
"""

from pydantic import BaseModel
from typing import Optional


class PromptTemplateCreate(BaseModel):
    """创建提示词模板"""
    business_line_id: int
    template_code: str
    name: str
    template_content: str
    variables: Optional[str] = None
    version: int = 1
    status: int = 1
    is_active: int = 0


class PromptTemplateUpdate(BaseModel):
    """更新提示词模板"""
    name: Optional[str] = None
    template_content: Optional[str] = None
    variables: Optional[str] = None
    version: Optional[int] = None
    status: Optional[int] = None
    is_active: Optional[int] = None


class PromptTemplateResponse(BaseModel):
    """提示词模板响应"""
    id: int
    business_line_id: int
    business_line_name: Optional[str] = None
    template_code: str
    name: str
    template_content: str
    variables: Optional[str]
    version: int
    status: int
    is_active: int
    created_at: str
    updated_at: str