"""门户（客户控制台）路由聚合

/public 前缀的接口无需登录（注册、登录、找回密码），
其余接口统一挂载 get_portal_user 依赖，租户只从令牌取。
"""

from fastapi import APIRouter, Depends

from src.api.deps.portal import get_portal_user
from . import auth, overview, projects, tasks, leads, stats, onboarding

# 需要登录的路由：依赖写在 router 上，新增子路由自动继承
authed = APIRouter(dependencies=[Depends(get_portal_user)])
authed.include_router(auth.authed_router)
authed.include_router(overview.router)
authed.include_router(projects.router)
authed.include_router(tasks.router)
authed.include_router(leads.router)
authed.include_router(stats.router)
authed.include_router(onboarding.router)

router = APIRouter()
router.include_router(auth.public_router)
router.include_router(authed)
