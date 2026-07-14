"""
账号配置路由
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.account import AccountCreate, AccountUpdate, AccountResponse
from src.api.utils.operation_log import log_operation

router = APIRouter()


@router.get("/", response_model=ApiResponse[List[AccountResponse]])
def list_accounts(
    platform_id: Optional[int] = None,
    status: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取账号列表"""
    sql = """
        SELECT a.*, p.name as platform_name 
        FROM accounts a 
        LEFT JOIN platforms p ON a.platform_id = p.id
    """
    conditions = []
    params = {}
    
    if platform_id is not None:
        conditions.append("a.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if status is not None:
        conditions.append("a.status = :status")
        params["status"] = status
    
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    
    sql += " ORDER BY a.created_at DESC"
    
    cursor = db.execute(text(sql), params)
    rows = cursor.fetchall()
    
    accounts = []
    for row in rows:
        accounts.append(AccountResponse(
            id=row.id,
            account_name=row.account_name,
            platform_id=row.platform_id,
            platform_name=row.platform_name,
            browser_id=row.browser_id,
            status=row.status,
            notes=row.notes,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at)
        ))
    
    return ApiResponse(result=accounts)


@router.get("/{account_id}", response_model=ApiResponse[AccountResponse])
def get_account(account_id: int, db: Session = Depends(get_db)):
    """获取账号详情"""
    sql = """
        SELECT a.*, p.name as platform_name 
        FROM accounts a 
        LEFT JOIN platforms p ON a.platform_id = p.id
        WHERE a.id = :id
    """
    cursor = db.execute(text(sql), {"id": account_id})
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="账号不存在")
    
    return ApiResponse(result=AccountResponse(
        id=row.id,
        account_name=row.account_name,
        platform_id=row.platform_id,
        platform_name=row.platform_name,
        browser_id=row.browser_id,
        status=row.status,
        notes=row.notes,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at)
    ))


@router.post("/", response_model=ApiResponse[AccountResponse])
def create_account(data: AccountCreate, request: Request, db: Session = Depends(get_db)):
    """创建账号"""
    # 验证平台是否存在
    platform_query = text("SELECT * FROM platforms WHERE id = :id")
    cursor = db.execute(platform_query, {"id": data.platform_id})
    if not cursor.fetchone():
        return ApiResponse(code=400, message="所选平台不存在")
    
    try:
        query = text("""
            INSERT INTO accounts (account_name, platform_id, browser_id, notes)
            VALUES (:account_name, :platform_id, :browser_id, :notes)
        """)
        cursor = db.execute(query, {
            "account_name": data.account_name,
            "platform_id": data.platform_id,
            "browser_id": data.browser_id,
            "notes": data.notes,
        })
        account_id = cursor.lastrowid
        db.commit()
        
        # 先查询账号数据，再记录操作日志（避免 log_operation 的 commit 影响 session 状态）
        result = get_account(account_id, db)
        
        # 记录操作日志
        client_ip = request.client.host if request.client else None
        log_operation(
            db=db,
            operation_type="创建账号",
            target_type="account",
            target_id=account_id,
            operation_detail=f"创建账号: {data.account_name}",
            ip_address=client_ip,
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{account_id}", response_model=ApiResponse[AccountResponse])
def update_account(account_id: int, data: AccountUpdate, request: Request, db: Session = Depends(get_db)):
    """更新账号"""
    cursor = db.execute(text("SELECT * FROM accounts WHERE id = :id"), {"id": account_id})
    row = cursor.fetchone()
    
    if not row:
        return ApiResponse(code=404, message="账号不存在")
    
    # 如果修改平台，验证平台是否存在
    if data.platform_id is not None:
        platform_query = text("SELECT * FROM platforms WHERE id = :id")
        cursor = db.execute(platform_query, {"id": data.platform_id})
        if not cursor.fetchone():
            return ApiResponse(code=400, message="所选平台不存在")
    
    updates = []
    params = {"id": account_id}
    
    if data.account_name is not None:
        updates.append("account_name = :account_name")
        params["account_name"] = data.account_name
    if data.platform_id is not None:
        updates.append("platform_id = :platform_id")
        params["platform_id"] = data.platform_id
    if data.browser_id is not None:
        updates.append("browser_id = :browser_id")
        params["browser_id"] = data.browser_id
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status
    if data.notes is not None:
        updates.append("notes = :notes")
        params["notes"] = data.notes
    
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE accounts SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()
    
    # 先查询数据，再记录操作日志（避免 log_operation 的 commit 影响 session 状态）
    result = get_account(account_id, db)
    
    if updates:
        client_ip = request.client.host if request.client else None
        log_operation(
            db=db,
            operation_type="编辑账号",
            target_type="account",
            target_id=account_id,
            operation_detail=f"编辑账号ID: {account_id}",
            ip_address=client_ip,
        )
    
    return result


@router.delete("/{account_id}", response_model=ApiResponse[dict])
def delete_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    """删除账号"""
    cursor = db.execute(text("SELECT * FROM accounts WHERE id = :id"), {"id": account_id})
    row = cursor.fetchone()
    
    if not row:
        return ApiResponse(code=404, message="账号不存在")
    
    # 检查是否有任务使用该账号
    task_query = text("SELECT COUNT(*) FROM task_executions WHERE account_id = :id")
    cursor = db.execute(task_query, {"id": account_id})
    count = cursor.fetchone()[0]
    if count > 0:
        return ApiResponse(code=400, message=f"该账号已被 {count} 个任务使用，无法删除")
    
    db.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})
    db.commit()
    
    # 记录操作日志
    client_ip = request.client.host if request.client else None
    log_operation(
        db=db,
        operation_type="删除账号",
        target_type="account",
        target_id=account_id,
        operation_detail=f"删除账号: {row.account_name}",
        ip_address=client_ip,
    )
    
    return ApiResponse(result={"message": "账号删除成功"})
