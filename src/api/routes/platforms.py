"""
平台配置路由
"""

import time
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.platform import PlatformCreate, PlatformUpdate, PlatformResponse

router = APIRouter()


def _generate_platform_code() -> str:
    """生成平台编码，格式: platform_{timestamp后8位}_{随机4位数字}"""
    ts = str(int(time.time()))[-8:]
    rand = str(random.randint(1000, 9999))
    return f"platform_{ts}_{rand}"


@router.get("/", response_model=ApiResponse[List[PlatformResponse]])
def list_platforms(status: Optional[int] = None, db: Session = Depends(get_db)):
    """获取平台列表"""
    if status is not None:
        query = text("SELECT * FROM platforms WHERE status = :status ORDER BY created_at")
        cursor = db.execute(query, {"status": status})
    else:
        query = text("SELECT * FROM platforms ORDER BY created_at")
        cursor = db.execute(query)
    
    rows = cursor.fetchall()
    
    platforms = []
    for row in rows:
        platforms.append(PlatformResponse(
            id=row.id,
            code=row.code,
            name=row.name,
            status=row.status,
            config=row.config,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at)
        ))
    
    return ApiResponse(result=platforms)


@router.post("/", response_model=ApiResponse[PlatformResponse])
def create_platform(data: PlatformCreate, db: Session = Depends(get_db)):
    """创建平台"""
    platform_code = data.code or _generate_platform_code()
    
    try:
        query = text("""INSERT INTO platforms (code, name, status, config)
           VALUES (:code, :name, :status, :config)""")
        
        cursor = db.execute(query, {
            "code": platform_code,
            "name": data.name,
            "status": data.status,
            "config": data.config
        })
        db.commit()
        
        platform_id = cursor.lastrowid
        
        query = text("SELECT * FROM platforms WHERE id = :id")
        cursor = db.execute(query, {"id": platform_id})
        row = cursor.fetchone()
        
        return ApiResponse(result=PlatformResponse(
            id=row.id,
            code=row.code,
            name=row.name,
            status=row.status,
            config=row.config,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at)
        ))
    except Exception as e:
        db.rollback()
        if "UNIQUE constraint" in str(e):
            return ApiResponse(code=400, message=f"平台编码 '{platform_code}' 已存在")
        raise


@router.put("/{platform_id}", response_model=ApiResponse[PlatformResponse])
def update_platform(platform_id: int, data: PlatformUpdate, db: Session = Depends(get_db)):
    """更新平台"""
    query = text("SELECT * FROM platforms WHERE id = :id")
    cursor = db.execute(query, {"id": platform_id})
    row = cursor.fetchone()
    
    if not row:
        return ApiResponse(code=404, message="平台不存在")
    
    updates = []
    params = {"id": platform_id}
    
    if data.name is not None:
        updates.append("name = :name")
        params["name"] = data.name
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status
    if data.config is not None:
        updates.append("config = :config")
        params["config"] = data.config
    
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE platforms SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()
    
    query = text("SELECT * FROM platforms WHERE id = :id")
    cursor = db.execute(query, {"id": platform_id})
    row = cursor.fetchone()
    
    return ApiResponse(result=PlatformResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        status=row.status,
        config=row.config,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at)
    ))


@router.delete("/{platform_id}", response_model=ApiResponse[dict])
def delete_platform(platform_id: int, db: Session = Depends(get_db)):
    """删除平台"""
    query = text("SELECT * FROM platforms WHERE id = :id")
    cursor = db.execute(query, {"id": platform_id})
    row = cursor.fetchone()
    
    if not row:
        return ApiResponse(code=404, message="平台不存在")
    
    db.execute(text("DELETE FROM platforms WHERE id = :id"), {"id": platform_id})
    db.commit()
    
    return ApiResponse(result={"message": "Platform deleted successfully"})
