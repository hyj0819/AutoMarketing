"""任务中心：列表 + 队列视图、新建、启动 / 停止 / 重试、任务详情"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user, require_role
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.task import (
    TaskCreate,
    TaskDetail,
    TaskHitItem,
    TaskItem,
    TaskListResult,
    TaskLogItem,
)
from src.core.database import get_db
from ._common import build_scrape_task_config, duration_minutes, queue_map, status_label, task_hits_bulk

router = APIRouter()

TYPE_LABEL = {'scrape': '采集', 'message': '私信', 'reply': '评论回复', 'reach': '采集 + 触达'}


@router.get("/tasks", response_model=ApiResponse[TaskListResult])
def list_tasks(
    status: str = None,
    business_line_id: int = None,
    task_type: str = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """任务列表（含排队位次与预计等待）"""
    conditions = ["te.tenant_id = :tid"]
    params: dict = {"tid": ctx.tenant_id}

    if status:
        conditions.append("te.status = :st")
        params["st"] = status
    if business_line_id:
        conditions.append("te.business_line_id = :bl")
        params["bl"] = business_line_id
    if task_type:
        conditions.append("te.task_type = :tt")
        params["tt"] = task_type
    if ctx.visible_scope:
        ids = ",".join(str(i) for i in ctx.visible_scope)
        conditions.append(f"te.business_line_id IN ({ids})")

    where = " AND ".join(conditions)
    total = db.execute(
        text(f"SELECT COUNT(*) AS cnt FROM task_executions te WHERE {where}"), params
    ).fetchone().cnt

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    rows = db.execute(
        text(f"""
            SELECT te.*, bl.name AS business_line_name, p.name AS platform_name
            FROM task_executions te
            LEFT JOIN business_lines bl ON te.business_line_id = bl.id
            LEFT JOIN platforms p ON bl.platform_id = p.id
            WHERE {where}
            ORDER BY te.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).fetchall()

    positions = queue_map(db, ctx.tenant_id)
    hits = task_hits_bulk(db, [r.id for r in rows])
    items = [_build_item(r, positions, hits) for r in rows]

    return ApiResponse(result=TaskListResult(items=items, total=total, page=page, page_size=page_size))


@router.post("/tasks", response_model=ApiResponse[TaskItem])
def create_task(
    data: TaskCreate,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """新建任务（进入 pending，调用启动接口后入队）

    托管模式下客户不碰执行层：采集深度、超时、风控节奏由平台决定，
    这里只让客户决定跑哪个项目、跑多少条。
    """
    bl = db.execute(
        text("SELECT * FROM business_lines WHERE id = :id AND tenant_id = :tid"),
        {"id": data.business_line_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="项目不存在")

    task_type = data.task_type if data.task_type in ('scrape', 'reach') else 'scrape'
    limit = max(1, min(int(data.limit or 240), 1000))

    if task_type == 'scrape':
        task_config, total, _kw_count = build_scrape_task_config(db, bl.id, limit)
        name = data.task_name or f"采集-{bl.name}"
    else:
        ids = [r[0] for r in db.execute(
            text("""
                SELECT id FROM contacts
                WHERE business_line_id = :bl AND contact_status = 'pending'
                ORDER BY id ASC LIMIT :lim
            """),
            {"bl": bl.id, "lim": limit},
        ).fetchall()]
        if not ids:
            raise HTTPException(status_code=400, detail="没有待触达的线索，先跑一次采集")
        task_config = json.dumps({
            "target_contact_ids": ids,
            "message_mode": "personalized",
        }, ensure_ascii=False)
        total = len(ids)
        name = data.task_name or f"触达-{bl.name}"

    cursor = db.execute(
        text("""
            INSERT INTO task_executions
                (tenant_id, task_name, task_type, business_line_id, status, task_config,
                 total_items, pending_items)
            VALUES (:tid, :name, :tt, :bl, 'pending', :cfg, :total, :total)
        """),
        {"tid": ctx.tenant_id, "name": name, "tt": task_type, "bl": bl.id, "cfg": task_config, "total": total},
    )
    task_id = cursor.lastrowid
    db.execute(
        text("INSERT INTO task_logs (task_id, log_level, message) VALUES (:t, 'info', '任务已创建，等待启动')"),
        {"t": task_id},
    )
    db.commit()

    return ApiResponse(result=_task_item(db, ctx, task_id))


@router.get("/tasks/{task_id}", response_model=ApiResponse[TaskDetail])
def get_task(task_id: int, ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """任务详情：进度、成功/失败/待处理计数、实时日志、命中线索预览"""
    task = _task_item(db, ctx, task_id)

    logs = db.execute(
        text("""
            SELECT * FROM task_logs WHERE task_id = :t ORDER BY created_at ASC, id ASC LIMIT 200
        """),
        {"t": task_id},
    ).fetchall()

    hit_rows = db.execute(
        text("""
            SELECT c.id, c.username, c.platform_user_id, c.source_keyword, c.contact_status,
                   c.metadata, c.notes
            FROM contact_interactions ci
            JOIN contacts c ON c.id = ci.contact_id
            WHERE ci.task_execution_id = :t AND ci.interaction_type = 'scraped'
            GROUP BY c.id
            ORDER BY c.id DESC
            LIMIT 20
        """),
        {"t": task_id},
    ).fetchall()

    hits = []
    for r in hit_rows:
        comment = ''
        try:
            meta = json.loads(r.metadata or '{}')
            comment = meta.get('comment') or meta.get('content_text') or ''
        except (ValueError, TypeError):
            comment = ''
        hits.append(TaskHitItem(
            id=r.id,
            username=r.username or r.platform_user_id,
            comment=(comment or '')[:140],
            source_keyword=r.source_keyword,
            ai_level=_ai_level(r.metadata),
            status=r.contact_status,
            status_label=_lead_status_label(r.contact_status),
        ))

    return ApiResponse(result=TaskDetail(
        task=task,
        logs=[TaskLogItem(id=l.id, log_level=l.log_level, message=l.message, created_at=str(l.created_at)) for l in logs],
        hits=hits,
    ))


@router.post("/tasks/{task_id}/start", response_model=ApiResponse[TaskItem])
def start_task(
    task_id: int,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """启动：pending -> queued，由平台侧 Worker 认领执行"""
    row = _raw_task(db, ctx, task_id)
    if row.status != 'pending':
        raise HTTPException(status_code=400, detail="只能启动待启动状态的任务")
    db.execute(
        text("UPDATE task_executions SET status = 'queued', updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": task_id},
    )
    db.execute(
        text("INSERT INTO task_logs (task_id, log_level, message) VALUES (:t, 'info', '任务已加入执行队列')"),
        {"t": task_id},
    )
    db.commit()
    return ApiResponse(result=_task_item(db, ctx, task_id))


@router.post("/tasks/{task_id}/stop", response_model=ApiResponse[TaskItem])
def stop_task(
    task_id: int,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """停止排队中或运行中的任务"""
    row = _raw_task(db, ctx, task_id)
    if row.status not in ('queued', 'running'):
        raise HTTPException(status_code=400, detail="只能停止排队中或运行中的任务")
    db.execute(
        text("""
            UPDATE task_executions
            SET status = 'cancelled', end_time = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {"id": task_id},
    )
    db.execute(
        text("INSERT INTO task_logs (task_id, log_level, message) VALUES (:t, 'warn', '任务被手动停止')"),
        {"t": task_id},
    )
    db.commit()
    return ApiResponse(result=_task_item(db, ctx, task_id))


@router.post("/tasks/{task_id}/retry", response_model=ApiResponse[TaskItem])
def retry_task(
    task_id: int,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """重试失败或已停止的任务，原地重置进度后重新入队"""
    row = _raw_task(db, ctx, task_id)
    if row.status not in ('failed', 'cancelled'):
        raise HTTPException(status_code=400, detail="只能重试失败或已停止的任务")
    db.execute(
        text("""
            UPDATE task_executions
            SET status = 'queued', progress = 0, success_items = 0, failed_items = 0,
                pending_items = total_items, error_message = NULL,
                start_time = NULL, end_time = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {"id": task_id},
    )
    db.execute(
        text("INSERT INTO task_logs (task_id, log_level, message) VALUES (:t, 'info', '任务已重新加入执行队列')"),
        {"t": task_id},
    )
    db.commit()
    return ApiResponse(result=_task_item(db, ctx, task_id))


# ---------------- 内部函数 ----------------

def _raw_task(db: Session, ctx: TenantContext, task_id: int):
    row = db.execute(
        text("SELECT * FROM task_executions WHERE id = :id AND tenant_id = :tid"),
        {"id": task_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if ctx.visible_scope and row.business_line_id and row.business_line_id not in ctx.visible_scope:
        raise HTTPException(status_code=403, detail="该任务不在你的可见范围内")
    return row


def _task_item(db: Session, ctx: TenantContext, task_id: int) -> TaskItem:
    row = db.execute(
        text("""
            SELECT te.*, bl.name AS business_line_name, p.name AS platform_name
            FROM task_executions te
            LEFT JOIN business_lines bl ON te.business_line_id = bl.id
            LEFT JOIN platforms p ON bl.platform_id = p.id
            WHERE te.id = :id AND te.tenant_id = :tid
        """),
        {"id": task_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    positions = queue_map(db, ctx.tenant_id)
    hits = task_hits_bulk(db, [row.id])
    return _build_item(row, positions, hits)


def _build_item(row, positions: dict, hits: dict) -> TaskItem:
    pos, eta = positions.get(row.id, (None, None))
    return TaskItem(
        id=row.id,
        task_name=row.task_name or f"任务 #{row.id}",
        task_type=row.task_type,
        task_type_label=TYPE_LABEL.get(row.task_type, row.task_type),
        business_line_id=row.business_line_id,
        business_line_name=getattr(row, "business_line_name", None),
        platform_name=getattr(row, "platform_name", None),
        status=row.status,
        status_label=status_label(row.status),
        progress=int(row.progress or 0),
        total_items=int(row.total_items or 0),
        success_items=int(row.success_items or 0),
        failed_items=int(row.failed_items or 0),
        pending_items=int(row.pending_items or 0),
        hits=hits.get(row.id, 0),
        created_at=str(row.created_at),
        start_time=str(row.start_time) if row.start_time else None,
        end_time=str(row.end_time) if row.end_time else None,
        duration_minutes=duration_minutes(row),
        queue_position=pos,
        eta_minutes=eta,
        error_message=row.error_message,
    )


def _ai_level(raw_metadata) -> str:
    """从 metadata 里读 AI 意向等级，读不到就按中处理"""
    try:
        meta = json.loads(raw_metadata or '{}')
    except (ValueError, TypeError):
        return '中'
    for key in ('ai_level', 'intent_level', 'level'):
        if meta.get(key):
            return str(meta[key])
    return '中'


def _lead_status_label(status: str) -> str:
    return {
        'pending': '待触达', 'contacted': '已触达', 'replied': '已回复', 'engaged': '有效对话',
        'qualified': '已确认需求', 'won': '已成交', 'lost': '已丢单', 'invalid': '误判', 'snoozed': '稍后联系',
    }.get(status, status)
