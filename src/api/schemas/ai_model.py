"""
AI模型配置 Schema
"""

from typing import Optional
from pydantic import BaseModel, Field


class AIModelBase(BaseModel):
    """AI模型基础字段"""
    provider: str = Field(..., description="Provider类型: deepseek/openai/anthropic/google/ollama/custom")
    api_url: Optional[str] = Field(None, description="API URL")


class AIModelCreate(AIModelBase):
    """创建AI模型"""
    api_key: str = Field(..., description="API Key (将加密存储)")


class AIModelUpdate(BaseModel):
    """更新AI模型"""
    api_key: Optional[str] = Field(None, description="API Key (留空表示不修改)")
    api_url: Optional[str] = None
    status: Optional[int] = Field(None, description="状态: 0-禁用 1-启用")


class AIModelResponse(BaseModel):
    """AI模型响应"""
    id: int
    provider: str
    api_key_masked: str
    api_url: Optional[str]
    is_active: int
    status: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TestAIModelRequest(BaseModel):
    """测试AI模型请求"""
    test_prompt: Optional[str] = Field("Hello, world!", description="测试Prompt")


class TestAIModelResponse(BaseModel):
    """测试AI模型响应"""
    success: bool
    response: str