"""
AI模型配置 Schema
"""

from typing import Optional
from pydantic import BaseModel, Field


class AIModelBase(BaseModel):
    """AI模型基础字段"""
    provider: str = Field(..., description="Provider类型: deepseek/openai/anthropic/google/ollama/custom")
    model_name: str = Field(..., description="模型名称")
    base_url: Optional[str] = Field(None, description="API Base URL")
    max_tokens: int = Field(2000, description="最大Token数")
    temperature: int = Field(70, description="温度系数 (0-100)")
    top_p: int = Field(90, description="Top P (0-100)")
    extra_params: Optional[str] = Field(None, description="额外参数 JSON")
    description: Optional[str] = Field(None, description="描述")


class AIModelCreate(AIModelBase):
    """创建AI模型"""
    api_key: str = Field(..., description="API Key (将加密存储)")


class AIModelUpdate(BaseModel):
    """更新AI模型"""
    api_key: Optional[str] = Field(None, description="API Key (留空表示不修改)")
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[int] = None
    top_p: Optional[int] = None
    extra_params: Optional[str] = None
    status: Optional[int] = Field(None, description="状态: 0-禁用 1-启用")
    description: Optional[str] = None


class AIModelResponse(BaseModel):
    """AI模型响应"""
    id: int
    provider: str
    model_name: str
    api_key_masked: str
    base_url: Optional[str]
    max_tokens: int
    temperature: int
    top_p: int
    extra_params: Optional[str]
    is_active: int
    status: int
    description: Optional[str]
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
