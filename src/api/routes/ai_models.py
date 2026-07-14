"""
AI模型配置路由
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from src.core.database import get_db
from src.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from src.api.schemas.common import ApiResponse
from src.api.schemas.ai_model import (
    AIModelCreate, AIModelUpdate, AIModelResponse,
    TestAIModelRequest, TestAIModelResponse
)

router = APIRouter()


@router.get("/", response_model=ApiResponse[List[AIModelResponse]])
def list_ai_models(
    provider: Optional[str] = None,
    status: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取AI模型列表"""
    if provider:
        query = text("SELECT * FROM ai_models WHERE provider = :provider ORDER BY created_at DESC")
        cursor = db.execute(query, {"provider": provider})
    elif status is not None:
        query = text("SELECT * FROM ai_models WHERE status = :status ORDER BY created_at DESC")
        cursor = db.execute(query, {"status": status})
    else:
        query = text("SELECT * FROM ai_models ORDER BY created_at DESC")
        cursor = db.execute(query)
    
    rows = cursor.fetchall()
    
    models = []
    for row in rows:
        api_key = decrypt_api_key(row.api_key_encrypted)
        models.append(AIModelResponse(
            id=row.id,
            provider=row.provider,
            model_name=row.model_name,
            api_key_masked=mask_api_key(api_key) if api_key else "",
            base_url=row.base_url,
            max_tokens=row.max_tokens,
            temperature=row.temperature,
            top_p=row.top_p,
            extra_params=row.extra_params,
            is_active=row.is_active,
            status=row.status,
            description=row.description,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at)
        ))
    
    return ApiResponse(result=models)


@router.get("/{model_id}", response_model=ApiResponse[AIModelResponse])
def get_ai_model(model_id: int, db: Session = Depends(get_db)):
    """获取AI模型详情"""
    query = text("SELECT * FROM ai_models WHERE id = :id")
    cursor = db.execute(query, {"id": model_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    
    api_key = decrypt_api_key(row.api_key_encrypted)
    return ApiResponse(result=AIModelResponse(
        id=row.id,
        provider=row.provider,
        model_name=row.model_name,
        api_key_masked=mask_api_key(api_key) if api_key else "",
        base_url=row.base_url,
        max_tokens=row.max_tokens,
        temperature=row.temperature,
        top_p=row.top_p,
        extra_params=row.extra_params,
        is_active=row.is_active,
        status=row.status,
        description=row.description,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at)
    ))


@router.post("/", response_model=ApiResponse[AIModelResponse])
def create_ai_model(data: AIModelCreate, db: Session = Depends(get_db)):
    """创建AI模型"""
    encrypted_key = encrypt_api_key(data.api_key)
    
    query = text("""INSERT INTO ai_models 
       (provider, model_name, api_key_encrypted, base_url, max_tokens, temperature, top_p, extra_params, description)
       VALUES (:provider, :model_name, :api_key_encrypted, :base_url, :max_tokens, :temperature, :top_p, :extra_params, :description)""")
    
    try:
        db.execute(query, {
            "provider": data.provider,
            "model_name": data.model_name,
            "api_key_encrypted": encrypted_key,
            "base_url": data.base_url,
            "max_tokens": data.max_tokens,
            "temperature": data.temperature,
            "top_p": data.top_p,
            "extra_params": data.extra_params,
            "description": data.description
        })
        db.commit()
    except Exception as e:
        db.rollback()
        if "UNIQUE constraint failed" in str(e):
            return ApiResponse(code=400, message=f"模型 {data.provider}/{data.model_name} 已存在")
        raise
    
    query = text("SELECT last_insert_rowid() as id")
    cursor = db.execute(query)
    model_id = cursor.fetchone()[0]
    
    return get_ai_model(model_id, db)


@router.put("/{model_id}", response_model=ApiResponse[AIModelResponse])
def update_ai_model(model_id: int, data: AIModelUpdate, db: Session = Depends(get_db)):
    """更新AI模型"""
    query = text("SELECT * FROM ai_models WHERE id = :id")
    cursor = db.execute(query, {"id": model_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    
    updates = []
    params = {"id": model_id}
    
    if data.api_key is not None:
        updates.append("api_key_encrypted = :api_key_encrypted")
        params["api_key_encrypted"] = encrypt_api_key(data.api_key)
    if data.base_url is not None:
        updates.append("base_url = :base_url")
        params["base_url"] = data.base_url
    if data.max_tokens is not None:
        updates.append("max_tokens = :max_tokens")
        params["max_tokens"] = data.max_tokens
    if data.temperature is not None:
        updates.append("temperature = :temperature")
        params["temperature"] = data.temperature
    if data.top_p is not None:
        updates.append("top_p = :top_p")
        params["top_p"] = data.top_p
    if data.extra_params is not None:
        updates.append("extra_params = :extra_params")
        params["extra_params"] = data.extra_params
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status
    if data.description is not None:
        updates.append("description = :description")
        params["description"] = data.description
    
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE ai_models SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()
    
    return get_ai_model(model_id, db)


@router.post("/{model_id}/activate", response_model=ApiResponse[dict])
def activate_ai_model(model_id: int, db: Session = Depends(get_db)):
    """激活AI模型"""
    query = text("SELECT * FROM ai_models WHERE id = :id")
    cursor = db.execute(query, {"id": model_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    
    if row.status != 1:
        raise HTTPException(status_code=400, detail="Model must be enabled before activation")
    
    db.execute(text("UPDATE ai_models SET is_active = 0 WHERE provider = :provider"), {"provider": row.provider})
    db.execute(text("UPDATE ai_models SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": model_id})
    db.commit()
    
    return ApiResponse(result={"message": "Model activated successfully"})


@router.post("/{model_id}/deactivate", response_model=ApiResponse[dict])
def deactivate_ai_model(model_id: int, db: Session = Depends(get_db)):
    """取消激活AI模型"""
    query = text("SELECT * FROM ai_models WHERE id = :id")
    cursor = db.execute(query, {"id": model_id})
    row = cursor.fetchone()
    
    if not row:
        return ApiResponse(code=404, message="模型不存在")
    
    db.execute(text("UPDATE ai_models SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": model_id})
    db.commit()
    
    return ApiResponse(result={"message": "Model deactivated successfully"})


@router.post("/{model_id}/test", response_model=ApiResponse[TestAIModelResponse])
def test_ai_model(model_id: int, data: TestAIModelRequest = None, db: Session = Depends(get_db)):
    """测试AI模型连接"""
    query = text("SELECT * FROM ai_models WHERE id = :id")
    cursor = db.execute(query, {"id": model_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    
    test_prompt = data.test_prompt if data else "Hello, world!"
    
    api_key = decrypt_api_key(row.api_key_encrypted)
    if not api_key:
        return ApiResponse(result=TestAIModelResponse(
            success=False,
            response="API Key is empty"
        ))
    
    try:
        import httpx
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        payload = {
            "model": row.model_name,
            "messages": [{"role": "user", "content": test_prompt}],
            "max_tokens": row.max_tokens,
            "temperature": row.temperature / 100
        }
        
        with httpx.Client(timeout=30) as client:
            response = client.post(f"{row.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return ApiResponse(result=TestAIModelResponse(
                success=True,
                response=result["choices"][0]["message"]["content"]
            ))
    except Exception as e:
        return ApiResponse(result=TestAIModelResponse(
            success=False,
            response=f"Connection failed: {str(e)}"
        ))


@router.delete("/{model_id}", response_model=ApiResponse[dict])
def delete_ai_model(model_id: int, db: Session = Depends(get_db)):
    """删除AI模型"""
    query = text("SELECT * FROM ai_models WHERE id = :id")
    cursor = db.execute(query, {"id": model_id})
    row = cursor.fetchone()
    
    if not row:
        return ApiResponse(code=404, message="模型不存在")
    
    if row.is_active == 1:
        return ApiResponse(code=400, message="该模型当前处于激活状态，请先取消激活后再删除")
    
    db.execute(text("DELETE FROM ai_models WHERE id = :id"), {"id": model_id})
    db.commit()
    
    return ApiResponse(result={"message": "Model deleted successfully"})
