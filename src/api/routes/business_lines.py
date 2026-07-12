"""
业务线配置路由
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.business_line import BusinessLineCreate, BusinessLineUpdate, BusinessLineResponse

router = APIRouter()


@router.get("/", response_model=ApiResponse[List[BusinessLineResponse]])
def list_business_lines(
    platform_id: Optional[int] = None,
    status: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取业务线列表"""
    # 使用 JOIN 查询平台名称
    base_query = """
        SELECT bl.*, p.name as platform_name 
        FROM business_lines bl
        LEFT JOIN platforms p ON bl.platform_id = p.id
    """
    conditions = []
    params = {}
    
    if platform_id:
        conditions.append("bl.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if status is not None:
        conditions.append("bl.status = :status")
        params["status"] = status
    
    query = base_query
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY bl.created_at"
    
    cursor = db.execute(text(query), params)
    rows = cursor.fetchall()
    
    lines = []
    for row in rows:
        lines.append(BusinessLineResponse(
            id=row.id,
            platform_id=row.platform_id,
            platform_name=row.platform_name,
            code=row.code,
            name=row.name,
            status=row.status,
            config=row.config,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at)
        ))
    
    return ApiResponse(result=lines)


@router.post("/", response_model=ApiResponse[BusinessLineResponse])
def create_business_line(data: BusinessLineCreate, db: Session = Depends(get_db)):
    """创建业务线"""
    query = text("SELECT * FROM platforms WHERE id = :id")
    cursor = db.execute(query, {"id": data.platform_id})
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="平台不存在")
    
    try:
        query = text("""INSERT INTO business_lines (platform_id, code, name, status, config)
           VALUES (:platform_id, :code, :name, :status, :config)""")
        
        cursor = db.execute(query, {
            "platform_id": data.platform_id,
            "code": data.code,
            "name": data.name,
            "status": data.status,
            "config": data.config
        })
        db.commit()
        
        line_id = cursor.lastrowid
        
        query = text("""
            SELECT bl.*, p.name as platform_name 
            FROM business_lines bl
            LEFT JOIN platforms p ON bl.platform_id = p.id
            WHERE bl.id = :id
        """)
        cursor = db.execute(query, {"id": line_id})
        row = cursor.fetchone()
        
        return ApiResponse(result=BusinessLineResponse(
            id=row.id,
            platform_id=row.platform_id,
            platform_name=row.platform_name,
            code=row.code,
            name=row.name,
            status=row.status,
            config=row.config,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at)
        ))
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="该平台下已存在相同编码的业务线")
        raise


@router.put("/{line_id}", response_model=ApiResponse[BusinessLineResponse])
def update_business_line(line_id: int, data: BusinessLineUpdate, db: Session = Depends(get_db)):
    """更新业务线"""
    query = text("SELECT * FROM business_lines WHERE id = :id")
    cursor = db.execute(query, {"id": line_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="业务线不存在")
    
    updates = []
    params = {"id": line_id}
    
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
        sql = text(f"UPDATE business_lines SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()
    
    query = text("""
        SELECT bl.*, p.name as platform_name 
        FROM business_lines bl
        LEFT JOIN platforms p ON bl.platform_id = p.id
        WHERE bl.id = :id
    """)
    cursor = db.execute(query, {"id": line_id})
    row = cursor.fetchone()
    
    return ApiResponse(result=BusinessLineResponse(
        id=row.id,
        platform_id=row.platform_id,
        platform_name=row.platform_name,
        code=row.code,
        name=row.name,
        status=row.status,
        config=row.config,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at)
    ))


@router.delete("/{line_id}", response_model=ApiResponse[dict])
def delete_business_line(line_id: int, db: Session = Depends(get_db)):
    """删除业务线"""
    query = text("SELECT * FROM business_lines WHERE id = :id")
    cursor = db.execute(query, {"id": line_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="业务线不存在")
    
    db.execute(text("DELETE FROM business_lines WHERE id = :id"), {"id": line_id})
    db.commit()
    
    return ApiResponse(result={"message": "业务线删除成功"})
