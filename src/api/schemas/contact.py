"""
触达用户 Schema
"""

from pydantic import BaseModel
from typing import Optional, List


class ContactCreate(BaseModel):
    """创建触达用户"""
    platform_id: int
    business_line_id: int
    platform_user_id: str
    username: Optional[str] = None
    profile_url: Optional[str] = None
    is_author: int = 0
    contact_status: str = 'pending'
    notes: Optional[str] = None
    metadata: Optional[str] = None


class ContactUpdate(BaseModel):
    """更新触达用户"""
    username: Optional[str] = None
    profile_url: Optional[str] = None
    is_author: Optional[int] = None
    contact_status: Optional[str] = None
    contact_attempts: Optional[int] = None
    last_contact_at: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[str] = None


class ContactResponse(BaseModel):
    """触达用户响应"""
    id: int
    platform_id: int
    platform_name: Optional[str] = None
    business_line_id: int
    business_line_name: Optional[str] = None
    platform_user_id: str
    username: Optional[str]
    profile_url: Optional[str]
    is_author: int
    contact_status: str
    contact_attempts: int
    last_contact_at: Optional[str]
    notes: Optional[str]
    metadata: Optional[str]
    created_at: str
    updated_at: str


class ContactInteractionCreate(BaseModel):
    """创建触达历史记录"""
    interaction_type: str
    task_execution_id: Optional[int] = None
    detail: Optional[str] = None


class ContactInteractionResponse(BaseModel):
    """触达历史记录响应"""
    id: int
    contact_id: int
    interaction_type: str
    task_execution_id: Optional[int]
    detail: Optional[str]
    created_at: str


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""
    ids: List[int]
    contact_status: str
