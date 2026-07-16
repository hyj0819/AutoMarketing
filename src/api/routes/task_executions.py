"""
任务执行管理路由
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.task_execution import (
    TaskScrapeCreate,
    TaskMessageCreate,
    TaskReplyCreate,
    TaskExecutionResponse,
    TaskListResponse,
    TaskLogResponse,
    TaskLogListResponse,
)

router = APIRouter()


def _build_task_response(row) -> dict:
    """从数据库行构建任务响应字典"""
    return {
        "id": row.id,
        "task_name": row.task_name,
        "task_type": row.task_type,
        "business_line_id": row.business_line_id,
        "business_line_name": getattr(row, "business_line_name", None),
        "platform_name": getattr(row, "platform_name", None),
        "status": row.status,
        "task_config": row.task_config,
        "total_items": row.total_items,
        "success_items": row.success_items,
        "failed_items": row.failed_items,
        "pending_items": row.pending_items,
        "progress": row.progress,
        "start_time": str(row.start_time) if row.start_time else None,
        "end_time": str(row.end_time) if row.end_time else None,
        "account_id": row.account_id,
        "error_message": row.error_message,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at) if hasattr(row, "updated_at") and row.updated_at else None,
    }


@router.get("/", response_model=ApiResponse[TaskListResponse])
def list_tasks(
    task_type: Optional[str] = None,
    business_line_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """获取任务列表（分页 + 筛选）"""
    conditions = []
    params: dict = {}

    if task_type:
        conditions.append("t.task_type = :task_type")
        params["task_type"] = task_type
    if business_line_id:
        conditions.append("t.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if status:
        conditions.append("t.status = :status")
        params["status"] = status
    if start_date:
        conditions.append("t.created_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("t.created_at <= :end_date")
        params["end_date"] = end_date + " 23:59:59"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * page_size

    # 查询总数
    count_sql = text(f"SELECT COUNT(*) as cnt FROM task_executions t {where_clause}")
    total = db.execute(count_sql, params).fetchone().cnt

    # 查询列表（关联业务线和平台名称）
    list_sql = text(f"""
        SELECT t.*,
               bl.name as business_line_name,
               p.name as platform_name
        FROM task_executions t
        LEFT JOIN business_lines bl ON t.business_line_id = bl.id
        LEFT JOIN platforms p ON bl.platform_id = p.id
        {where_clause}
        ORDER BY t.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    params["limit"] = page_size
    params["offset"] = offset
    rows = db.execute(list_sql, params).fetchall()

    items = [_build_task_response(row) for row in rows]

    return ApiResponse(
        result=TaskListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/{task_id}", response_model=ApiResponse[TaskExecutionResponse])
def get_task(task_id: int, db: Session = Depends(get_db)):
    """获取任务详情（含关联信息）"""
    query = text("""
        SELECT t.*,
               bl.name as business_line_name,
               p.name as platform_name
        FROM task_executions t
        LEFT JOIN business_lines bl ON t.business_line_id = bl.id
        LEFT JOIN platforms p ON bl.platform_id = p.id
        WHERE t.id = :id
    """)
    row = db.execute(query, {"id": task_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    return ApiResponse(result=TaskExecutionResponse(**_build_task_response(row)))


@router.post("/scrape", response_model=ApiResponse[TaskExecutionResponse])
def create_scrape_task(data: TaskScrapeCreate, db: Session = Depends(get_db)):
    """创建爬虫任务"""
    # 验证业务线
    bl = db.execute(
        text("SELECT * FROM business_lines WHERE id = :id"),
        {"id": data.business_line_id},
    ).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="业务线不存在")

    # 构建 task_config JSON
    task_config = json.dumps(
        {
            "keywords": data.keywords,
            "content_types": data.content_types,
            "max_items_per_keyword": data.max_items_per_keyword,
            "ai_filter_enabled": data.ai_filter_enabled,
            "ai_prompt_template_id": data.ai_prompt_template_id,
            "exclude_author": data.exclude_author,
        },
        ensure_ascii=False,
    )

    # 计算总采集量
    total_items = len(data.keywords) * data.max_items_per_keyword
    task_name = data.task_name or f"爬虫任务-{bl.name}"

    insert_sql = text("""
        INSERT INTO task_executions
            (task_name, task_type, business_line_id, status, task_config,
             total_items, pending_items, account_id)
        VALUES
            (:task_name, 'scrape', :business_line_id, 'pending', :task_config,
             :total_items, :total_items, :account_id)
    """)
    db.execute(
        insert_sql,
        {
            "task_name": task_name,
            "business_line_id": data.business_line_id,
            "task_config": task_config,
            "total_items": total_items,
            "account_id": data.account_id,
        },
    )
    db.commit()

    task_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]
    return get_task(task_id, db)


@router.post("/message", response_model=ApiResponse[TaskExecutionResponse])
def create_message_task(data: TaskMessageCreate, db: Session = Depends(get_db)):
    """创建私信任务"""
    bl = db.execute(
        text("SELECT * FROM business_lines WHERE id = :id"),
        {"id": data.business_line_id},
    ).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="业务线不存在")

    task_config = json.dumps(
        {
            "target_contact_ids": data.target_contact_ids,
            "message_mode": data.message_mode,
            "prompt_template_id": data.prompt_template_id,
            "fixed_message": data.fixed_message,
            "max_send_count": data.max_send_count,
            "send_interval_min": data.send_interval_min,
            "send_interval_max": data.send_interval_max,
        },
        ensure_ascii=False,
    )

    total_items = min(len(data.target_contact_ids), data.max_send_count)
    task_name = data.task_name or f"私信任务-{bl.name}"

    insert_sql = text("""
        INSERT INTO task_executions
            (task_name, task_type, business_line_id, status, task_config,
             total_items, pending_items, account_id)
        VALUES
            (:task_name, 'message', :business_line_id, 'pending', :task_config,
             :total_items, :total_items, :account_id)
    """)
    db.execute(
        insert_sql,
        {
            "task_name": task_name,
            "business_line_id": data.business_line_id,
            "task_config": task_config,
            "total_items": total_items,
            "account_id": data.account_id,
        },
    )
    db.commit()

    task_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]
    return get_task(task_id, db)


@router.post("/reply", response_model=ApiResponse[TaskExecutionResponse])
def create_reply_task(data: TaskReplyCreate, db: Session = Depends(get_db)):
    """创建评论回复任务"""
    bl = db.execute(
        text("SELECT * FROM business_lines WHERE id = :id"),
        {"id": data.business_line_id},
    ).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="业务线不存在")

    task_config = json.dumps(
        {
            "keywords": data.keywords,
            "prompt_template_id": data.prompt_template_id,
            "max_reply_count": data.max_reply_count,
        },
        ensure_ascii=False,
    )

    task_name = data.task_name or f"回复任务-{bl.name}"

    insert_sql = text("""
        INSERT INTO task_executions
            (task_name, task_type, business_line_id, status, task_config,
             total_items, pending_items, account_id)
        VALUES
            (:task_name, 'reply', :business_line_id, 'pending', :task_config,
             :total_items, :total_items, :account_id)
    """)
    db.execute(
        insert_sql,
        {
            "task_name": task_name,
            "business_line_id": data.business_line_id,
            "task_config": task_config,
            "total_items": data.max_reply_count,
            "account_id": data.account_id,
        },
    )
    db.commit()

    task_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]
    return get_task(task_id, db)


@router.post("/{task_id}/stop", response_model=ApiResponse[TaskExecutionResponse])
def stop_task(task_id: int, db: Session = Depends(get_db)):
    """停止任务"""
    row = db.execute(
        text("SELECT * FROM task_executions WHERE id = :id"), {"id": task_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status != "running":
        raise HTTPException(status_code=400, detail="只能停止运行中的任务")

    db.execute(
        text(
            "UPDATE task_executions SET status = 'cancelled', end_time = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
        ),
        {"id": task_id},
    )
    # 写入日志
    db.execute(
        text(
            "INSERT INTO task_logs (task_id, log_level, message) VALUES (:task_id, 'warn', '任务被手动停止')"
        ),
        {"task_id": task_id},
    )
    db.commit()

    return get_task(task_id, db)


@router.post("/{task_id}/retry", response_model=ApiResponse[TaskExecutionResponse])
def retry_task(task_id: int, db: Session = Depends(get_db)):
    """重试失败任务（复制配置创建新任务）"""
    row = db.execute(
        text("SELECT * FROM task_executions WHERE id = :id"), {"id": task_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=400, detail="只能重试失败或已取消的任务")

    # 复制配置创建新任务
    new_name = f"{row.task_name or '任务'}(重试)"
    insert_sql = text("""
        INSERT INTO task_executions
            (task_name, task_type, business_line_id, status, task_config,
             total_items, pending_items, account_id)
        VALUES
            (:task_name, :task_type, :business_line_id, 'pending', :task_config,
             :total_items, :total_items, :account_id)
    """)
    db.execute(
        insert_sql,
        {
            "task_name": new_name,
            "task_type": row.task_type,
            "business_line_id": row.business_line_id,
            "task_config": row.task_config,
            "total_items": row.total_items,
            "account_id": row.account_id,
        },
    )
    db.commit()

    new_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone().id

    # 写入日志
    db.execute(
        text(
            "INSERT INTO task_logs (task_id, log_level, message) VALUES (:task_id, 'info', :msg)"
        ),
        {"task_id": new_id, "msg": f"从任务 #{task_id} 重试创建"},
    )
    db.commit()

    return get_task(new_id, db)


@router.delete("/{task_id}", response_model=ApiResponse[dict])
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """删除任务（仅允许非 running 状态）"""
    row = db.execute(
        text("SELECT * FROM task_executions WHERE id = :id"), {"id": task_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status == "running":
        raise HTTPException(status_code=400, detail="运行中的任务不允许删除，请先停止")

    # 先删除关联日志
    db.execute(text("DELETE FROM task_logs WHERE task_id = :task_id"), {"task_id": task_id})
    db.execute(text("DELETE FROM task_executions WHERE id = :id"), {"id": task_id})
    db.commit()

    return ApiResponse(result={"message": "任务删除成功"})


# ==================== 任务日志接口 ====================


@router.get("/{task_id}/logs", response_model=ApiResponse[TaskLogListResponse])
def get_task_logs(
    task_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    log_level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取任务执行日志（分页）"""
    # 验证任务存在
    row = db.execute(
        text("SELECT id FROM task_executions WHERE id = :id"), {"id": task_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    conditions = ["task_id = :task_id"]
    params: dict = {"task_id": task_id}

    if log_level:
        conditions.append("log_level = :log_level")
        params["log_level"] = log_level

    where_clause = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * page_size

    # 总数
    count_sql = text(f"SELECT COUNT(*) as cnt FROM task_logs {where_clause}")
    total = db.execute(count_sql, params).fetchone().cnt

    # 列表
    list_sql = text(f"""
        SELECT * FROM task_logs
        {where_clause}
        ORDER BY created_at ASC
        LIMIT :limit OFFSET :offset
    """)
    params["limit"] = page_size
    params["offset"] = offset
    rows = db.execute(list_sql, params).fetchall()

    items = [
        TaskLogResponse(
            id=r.id,
            task_id=r.task_id,
            log_level=r.log_level,
            message=r.message,
            created_at=str(r.created_at),
        )
        for r in rows
    ]

    return ApiResponse(
        result=TaskLogListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    )