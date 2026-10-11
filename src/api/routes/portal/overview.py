"""控制台首页：配额、今日数据、待办、最近活动、任务队列"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.overview import (
    ActivityItem,
    OverviewResult,
    QueueItem,
    QuotaUsage,
    TodayStats,
    TodoItem,
)
from src.core.database import get_db
from ._common import REACHED_IN_SQL, days_left, duration_minutes, period_bounds, queue_map, status_label, task_hits_bulk

router = APIRouter()


@router.get("/overview", response_model=ApiResponse[OverviewResult])
def get_overview(ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    tenant = db.execute(
        text("SELECT * FROM tenants WHERE id = :tid"), {"tid": ctx.tenant_id}
    ).fetchone()
    if not tenant:
        return ApiResponse(code=404, message="租户不存在", result=None)

    start, end = period_bounds(tenant)
    today = datetime.now().strftime("%Y-%m-%d")

    # ---------- 配额 ----------
    reach_used = _scalar(db, """
        SELECT COUNT(*) FROM contacts
        WHERE tenant_id = :tid AND contact_status IN (%s)
          AND (last_contact_at IS NULL OR date(last_contact_at) >= :start)
    """ % REACHED_IN_SQL, {"tid": ctx.tenant_id, "start": start})

    # AI 调用口径：每条线索一次意图判断 + 每条触达一次话术生成
    ai_used = _scalar(db, """
        SELECT
            (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) >= :start)
            +
            (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND contact_status IN (%s)
                AND (last_contact_at IS NULL OR date(last_contact_at) >= :start))
    """ % REACHED_IN_SQL, {"tid": ctx.tenant_id, "start": start})

    seats_used = _scalar(db, """
        SELECT COUNT(*) FROM tenant_members WHERE tenant_id = :tid AND status = 1
    """, {"tid": ctx.tenant_id})

    reach_limit = tenant.quota_reach or 0
    quota = QuotaUsage(
        reach_used=reach_used,
        reach_limit=reach_limit,
        ai_used=ai_used,
        ai_limit=tenant.quota_ai_calls or 0,
        seats_used=seats_used,
        seats_limit=tenant.quota_seats or 0,
        period_start=start,
        period_end=end,
        days_left=days_left(end),
        forecast_exhaust_on=_forecast_exhaust_on(db, ctx.tenant_id, start, reach_used, reach_limit),
    )

    # ---------- 今日数据 ----------
    today_stats = _today_stats(db, ctx.tenant_id, today)

    # ---------- 待办 ----------
    todo = _todo_items(db, ctx.tenant_id)

    failed_task_count = _scalar(db, """
        SELECT COUNT(*) FROM task_executions WHERE tenant_id = :tid AND status = 'failed'
    """, {"tid": ctx.tenant_id})

    # ---------- 最近活动 ----------
    activities = _recent_activities(db, ctx.tenant_id, limit=8)

    # ---------- 队列 ----------
    queue = _queue_items(db, ctx.tenant_id)

    return ApiResponse(result=OverviewResult(
        quota=quota,
        today=today_stats,
        todo=todo,
        failed_task_count=failed_task_count,
        activities=activities,
        queue=queue,
    ))


# ---------------- 内部函数 ----------------

def _scalar(db: Session, sql: str, params: dict) -> int:
    row = db.execute(text(sql), params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _forecast_exhaust_on(db, tenant_id: int, start: str, used: int, limit: int):
    """按近 7 天日均触达速度，估算额度耗尽日期；额度用不完或已用完则返回 None"""
    if limit <= 0 or used >= limit:
        return None
    daily = _scalar(db, """
        SELECT COUNT(*) FROM contacts
        WHERE tenant_id = :tid AND contact_status IN (%s)
          AND date(last_contact_at) >= date('now', '-7 days')
    """ % REACHED_IN_SQL, {"tid": tenant_id})
    if daily <= 0:
        return None
    per_day = daily / 7.0
    days_needed = (limit - used) / per_day
    if days_needed > 365:
        return None
    return (datetime.now() + timedelta(days=int(days_needed) + 1)).strftime("%Y-%m-%d")


def _today_stats(db: Session, tenant_id: int, today: str) -> TodayStats:
    row = db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) = :d) AS new_leads,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND contact_status IN (%s)
                    AND date(last_contact_at) = :d) AS sent,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(replied_at) = :d) AS replies,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(won_at) = :d) AS won_count,
                (SELECT COALESCE(SUM(deal_amount), 0) FROM contacts WHERE tenant_id = :tid
                    AND date(won_at) = :d) AS won_amount
        """ % REACHED_IN_SQL),
        {"tid": tenant_id, "d": today},
    ).fetchone()

    new_leads = int(row.new_leads or 0)
    sent = int(row.sent or 0)
    replies = int(row.replies or 0)
    won_count = int(row.won_count or 0)
    won_amount = float(row.won_amount or 0)

    task_row = db.execute(
        text("""
            SELECT COALESCE(SUM(success_items), 0) AS ok, COALESCE(SUM(failed_items), 0) AS bad
            FROM task_executions
            WHERE tenant_id = :tid AND date(COALESCE(end_time, created_at)) = :d
              AND status IN ('success', 'failed', 'running')
        """),
        {"tid": tenant_id, "d": today},
    ).fetchone()
    ok, bad = int(task_row.ok or 0), int(task_row.bad or 0)
    delivery_rate = round(ok / (ok + bad) * 100, 1) if (ok + bad) else 0.0

    return TodayStats(
        new_leads=new_leads,
        sent=sent,
        replies=replies,
        won_count=won_count,
        won_amount=won_amount,
        reply_rate=round(replies / sent * 100, 1) if sent else 0.0,
        delivery_rate=delivery_rate,
    )


def _todo_items(db: Session, tenant_id: int) -> list:
    """待办按「该做什么」分组，不按时间排"""
    specs = [
        ("overdue_24h", "超过 24 小时没跟进的已回复线索", "danger", """
            SELECT COUNT(*) FROM contacts
            WHERE tenant_id = :tid AND contact_status = 'replied'
              AND COALESCE(replied_at, last_contact_at) < datetime('now', '-24 hours')
        """),
        ("new_reply", "今天新回复，还没处理", "warn", """
            SELECT COUNT(*) FROM contacts
            WHERE tenant_id = :tid AND contact_status IN ('replied', 'engaged')
              AND date(replied_at) = date('now')
        """),
        ("quoted_stale", "已报价，超过 3 天没动静", "warn", """
            SELECT COUNT(*) FROM contacts
            WHERE tenant_id = :tid AND quote_amount IS NOT NULL
              AND quoted_at < datetime('now', '-3 days')
              AND contact_status NOT IN ('won', 'lost')
        """),
        ("snoozed_due", "今天到期的「稍后联系」", "ok", """
            SELECT COUNT(*) FROM contacts
            WHERE tenant_id = :tid AND contact_status = 'snoozed'
              AND snooze_until IS NOT NULL AND date(snooze_until) <= date('now')
        """),
    ]
    items = []
    for kind, title, level, sql in specs:
        items.append(TodoItem(kind=kind, title=title, level=level, count=_scalar(db, sql, {"tid": tenant_id})))
    return items


def _recent_activities(db: Session, tenant_id: int, limit: int = 8) -> list:
    """最近活动：线索新增、成交/丢单登记、任务状态，三路合并"""
    rows = db.execute(
        text("""
            SELECT t, actor, title, detail, created_at FROM (
                SELECT 'lead' AS t, '系统' AS actor,
                       '新增线索：' || COALESCE(username, platform_user_id) AS title,
                       '来源关键词 ' || COALESCE(source_keyword, '未记录') AS detail,
                       created_at
                FROM contacts WHERE tenant_id = :tid

                UNION ALL

                SELECT 'status' AS t, COALESCE(l.operator, '成员') AS actor,
                       CASE l.to_status
                           WHEN 'won' THEN '登记成交'
                           WHEN 'lost' THEN '登记丢单'
                           WHEN 'qualified' THEN '标记为已确认需求'
                           WHEN 'engaged' THEN '标记为有效对话'
                           WHEN 'replied' THEN '标记为已回复'
                           WHEN 'contacted' THEN '标记为已触达'
                           ELSE '状态变更为 ' || l.to_status END AS title,
                       COALESCE(l.reason, l.note, '') AS detail,
                       l.created_at
                FROM lead_status_logs l
                JOIN contacts c ON c.id = l.contact_id
                WHERE c.tenant_id = :tid

                UNION ALL

                SELECT 'task' AS t, '系统' AS actor,
                       CASE te.status
                           WHEN 'success' THEN '任务执行完成：' || te.task_name
                           WHEN 'failed' THEN '任务执行失败：' || te.task_name
                           WHEN 'cancelled' THEN '任务被停止：' || te.task_name
                           ELSE '任务状态更新：' || te.task_name END AS title,
                       COALESCE(te.error_message, '') AS detail,
                       COALESCE(te.end_time, te.created_at) AS created_at
                FROM task_executions te
                WHERE te.tenant_id = :tid AND te.status IN ('success', 'failed', 'cancelled')
            )
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        {"tid": tenant_id, "lim": limit},
    ).fetchall()

    out = []
    for r in rows:
        out.append(ActivityItem(
            time=str(r.created_at)[:16],
            actor=r.actor or '系统',
            title=r.title,
            detail=(r.detail or None),
        ))
    return out


def _queue_items(db: Session, tenant_id: int) -> list:
    """队列视图：运行中 + 等待中 + 失败（失败单独给出重试入口）"""
    rows = db.execute(
        text("""
            SELECT te.*, bl.name AS business_line_name
            FROM task_executions te
            LEFT JOIN business_lines bl ON te.business_line_id = bl.id
            WHERE te.tenant_id = :tid AND te.status IN ('running', 'queued', 'failed')
            ORDER BY CASE te.status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                     te.created_at ASC
            LIMIT 20
        """),
        {"tid": tenant_id},
    ).fetchall()

    positions = queue_map(db, tenant_id)
    hits = task_hits_bulk(db, [r.id for r in rows])

    items = []
    for r in rows:
        pos, eta = positions.get(r.id, (None, None))
        items.append(QueueItem(
            id=r.id,
            task_name=r.task_name or f"任务 #{r.id}",
            status=r.status,
            status_label=status_label(r.status),
            progress=int(r.progress or 0),
            processed=int((r.success_items or 0) + (r.failed_items or 0)),
            total=int(r.total_items or 0),
            hits=hits.get(r.id, 0),
            business_line_name=getattr(r, "business_line_name", None),
            queue_position=pos,
            eta_minutes=eta,
            error_message=r.error_message,
        ))
    return items
