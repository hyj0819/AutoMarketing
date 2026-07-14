"""
FastAPI 应用入口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="AutoMarketing API",
    description="AutoMarketing 自动化营销平台 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

origins = os.getenv('CORS_ORIGINS', 'http://localhost:8001').split(',')
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from src.api.routes import ai_models, keywords, platforms, business_lines
from src.api.routes import prompt_templates, contacts, contents, task_executions, stats
from src.api.routes import accounts, operation_logs
from src.api.routes import auth, users, roles

app.include_router(ai_models.router, prefix="/api/config/ai-models", tags=["AI模型配置"])
app.include_router(keywords.router, prefix="/api/config/keywords", tags=["关键词管理"])
app.include_router(platforms.router, prefix="/api/config/platforms", tags=["平台配置"])
app.include_router(business_lines.router, prefix="/api/config/business-lines", tags=["业务线配置"])
app.include_router(prompt_templates.router, prefix="/api/config/prompt-templates", tags=["提示词管理"])
app.include_router(contacts.router, prefix="/api/contacts", tags=["触达用户"])
app.include_router(contents.router, prefix="/api/contents", tags=["内容数据"])
app.include_router(task_executions.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(stats.router, prefix="/api/stats", tags=["统计分析"])
app.include_router(accounts.router, prefix="/api/system/accounts", tags=["账号配置"])
app.include_router(operation_logs.router, prefix="/api/system/operation-logs", tags=["操作日志"])
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/system/users", tags=["用户管理"])
app.include_router(roles.router, prefix="/api/system/roles", tags=["角色管理"])


@app.get("/")
async def root():
    """根路径"""
    return {"message": "AutoMarketing API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}
