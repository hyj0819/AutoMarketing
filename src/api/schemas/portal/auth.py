"""门户鉴权相关模型"""

from typing import List, Optional

from pydantic import BaseModel


class MenuItem(BaseModel):
    """门户菜单项。key 一律带 portal: 前缀，与自用端菜单命名空间隔离"""

    key: str
    title: str
    path: str
    sort: int = 0


# 门户菜单：客户只能看到这些，不含任何运维页（系统配置、AI 模型、账号/代理/平台配置）
PORTAL_MENUS: List[MenuItem] = [
    MenuItem(key='portal:dashboard', title='控制台首页', path='/portal/dashboard', sort=1),
    MenuItem(key='portal:projects', title='项目管理', path='/portal/projects', sort=2),
    MenuItem(key='portal:tasks', title='任务中心', path='/portal/tasks', sort=3),
    MenuItem(key='portal:leads', title='线索池', path='/portal/leads', sort=4),
    MenuItem(key='portal:analytics', title='数据看板', path='/portal/analytics', sort=5),
]

MENUS_BY_ROLE = {
    'admin': ['portal:dashboard', 'portal:projects', 'portal:tasks', 'portal:leads', 'portal:analytics'],
    'operator': ['portal:dashboard', 'portal:projects', 'portal:tasks', 'portal:leads', 'portal:analytics'],
    'viewer': ['portal:dashboard', 'portal:projects', 'portal:tasks', 'portal:leads', 'portal:analytics'],
}


def menus_for_role(role: str) -> List[MenuItem]:
    """按角色返回可见菜单；未知角色按只读处理"""
    keys = MENUS_BY_ROLE.get(role, MENUS_BY_ROLE['viewer'])
    return [m for m in PORTAL_MENUS if m.key in keys]


class RegisterRequest(BaseModel):
    email: str
    password: str
    real_name: Optional[str] = None
    company_name: Optional[str] = None
    invite_token: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ResetPasswordRequest(BaseModel):
    email: str
    token: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class AccountInfo(BaseModel):
    id: int
    email: str
    real_name: Optional[str] = None
    role: str
    last_login_at: Optional[str] = None


class TenantBrief(BaseModel):
    id: int
    name: str
    plan_code: str
    quota_reach: int
    quota_ai_calls: int
    quota_seats: int
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    # 新手引导是租户级的，登录时就带出来，前端据此决定要不要先跳引导页
    onboarding_done: bool = False
    onboarding_step: int = 1


class TokenResult(BaseModel):
    access_token: str
    token_type: str = 'Bearer'
    expires_in_hours: int = 24


class LoginResult(BaseModel):
    token: TokenResult
    account: AccountInfo
    tenant: TenantBrief
    menus: List[MenuItem]


class UserInfoResult(BaseModel):
    account: AccountInfo
    tenant: TenantBrief
    menus: List[MenuItem]
