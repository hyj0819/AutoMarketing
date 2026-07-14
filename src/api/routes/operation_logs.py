"""
操作日志路由
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.operation_log import OperationLogResponse, OperationLogListResult

router = APIRouter()


@router.get("/", response_model=ApiResponse[OperationLogListResult])
def list_operation_logs(
    operation_type: Optional[str] = None,
    target_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db)
):
    """获取操作日志列表"""
    # 构建查询条件
    conditions = []
    params = {}
    
    if operation_type:
        conditions.append("operation_type LIKE :operation_type")
        params["operation_type"] = f"%{operation_type}%"
    if target_type:
        conditions.append("target_type = :target_type")
        params["target_type"] = target_type
    if start_date:
        conditions.append("created_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("created_at <= :end_date")
        params["end_date"] = end_date
    
    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    
    # 查询总数
    count_sql = f"SELECT COUNT(*) FROM operation_logs {where_clause}"
    cursor = db.execute(text(count_sql), params)
    total = cursor.fetchone()[0]
    
    # 查询分页数据
    offset = (page - 1) * page_size
    data_sql = f"""
        SELECT * FROM operation_logs {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = page_size
    params["offset"] = offset
    
    cursor = db.execute(text(data_sql), params)
    rows = cursor.fetchall()
    
    items = []
    for row in rows:
        items.append(OperationLogResponse(
            id=row.id,
            operation_type=row.operation_type,
            operator=row.operator,
            target_type=row.target_type,
            target_id=row.target_id,
            operation_detail=row.operation_detail,
            ip_address=row.ip_address,
            created_at=str(row.created_at)
        ))
    
    return ApiResponse(result=OperationLogListResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size
    ))


@router.get("/export", response_model=ApiResponse[list[OperationLogResponse]])
def export_operation_logs(
    operation_type: Optional[str] = None,
    target_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """导出操作日志"""
    conditions = []
    params = {}
    
    if operation_type:
        conditions.append("operation_type LIKE :operation_type")
        params["operation_type"] = f"%{operation_type}%"
    if target_type:
        conditions.append("target_type = :target_type")
        params["target_type"] = target_type
    if start_date:
        conditions.append("created_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("created_at <= :end_date")
        params["end_date"] = end_date
    
    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    
    sql = f"""
        SELECT * FROM operation_logs {where_clause}
        ORDER BY created_at DESC
        LIMIT 10000
    """
    
    cursor = db.execute(text(sql), params)
    rows = cursor.fetchall()
    
    items = []
    for row in rows:
        items.append(OperationLogResponse(
            id=row.id,
            operation_type=row.operation_type,
            operator=row.operator,
            target_type=row.target_type,
            target_id=row.target_id,
            operation_detail=row.operation_detail,
            ip_address=row.ip_address,
            created_at=str(row.created_at)
        ))
    
    return ApiResponse(result=items)


@router.get("/types", response_model=ApiResponse[dict])
def get_log_types(db: Session = Depends(get_db)):
    """获取操作日志的所有类型（用于筛选下拉框）"""
    # 获取所有不同的操作类型
    cursor = db.execute(text("SELECT DISTINCT operation_type FROM operation_logs ORDER BY operation_type"))
    operation_types = [row[0] for row in cursor.fetchall()]
    
    # 获取所有不同的目标类型
    cursor = db.execute(text("SELECT DISTINCT target_type FROM operation_logs WHERE target_type IS NOT NULL ORDER BY target_type"))
    target_types = [row[0] for row in cursor.fetchall()]
    
    return ApiResponse(result={
        "operation_types": operation_types,
        "target_types": target_types
    })
