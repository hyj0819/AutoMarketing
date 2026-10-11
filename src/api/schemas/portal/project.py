"""项目管理出参模型

字段裁剪：不暴露 config JSON（内含 chrome profile、代理、爬虫参数等运维面内容）、
不暴露 browser_id，账号只给名称与状态。
"""

from typing import List, Optional

from pydantic import BaseModel


class PlatformOption(BaseModel):
    id: int
    name: str
    code: str


class ProjectItem(BaseModel):
    id: int
    name: str
    platform_id: int
    platform_name: Optional[str] = None
    status: int = 1
    keyword_count: int = 0
    active_template: Optional[str] = None
    account_name: Optional[str] = None
    leads_count: int = 0
    reached_count: int = 0
    replied_count: int = 0
    reply_rate: float = 0
    updated_at: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str
    platform_id: int
    account_id: Optional[int] = None
    preset_template_id: Optional[int] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[int] = None
    account_id: Optional[int] = None


class AddKeywordsRequest(BaseModel):
    keywords: List[str]
    priority: int = 1


class KeywordItem(BaseModel):
    id: int
    keyword: str
    priority: int = 1
    status: int = 1
    hits: int = 0
    replies: int = 0
    won: int = 0
    won_amount: float = 0


class ScriptItem(BaseModel):
    id: int
    name: str
    version: int = 1
    status: int = 1
    is_active: int = 0
    is_preset: int = 0
    source: str = 'project'
    preview: str = ''
    reach: int = 0
    replies: int = 0
    reply_rate: float = 0


class AccountItem(BaseModel):
    id: int
    account_name: str
    platform_name: Optional[str] = None
    status: int = 1
    status_label: str = '正常'
    sent_today: int = 0
    reply_rate_7d: float = 0


class ProjectDetail(BaseModel):
    project: ProjectItem
    keywords: List[KeywordItem]
    scripts: List[ScriptItem]
    accounts: List[AccountItem]
    managed_pool_note: str = ''
