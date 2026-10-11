"""门户路由共用的查询片段

所有查询都必须带 tenant_id，租户只从令牌取，不接受前端传入。
"""

import json
import math
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

# 已触达及之后的状态（用于统计触达量与回复率）
REACHED_STATUSES = ("contacted", "replied", "engaged", "qualified", "won", "lost")
REACHED_IN_SQL = ", ".join(f"'{s}'" for s in REACHED_STATUSES)


def period_bounds(row) -> Tuple[str, str]:
    """结算周期：租户没配置时退化为自然月"""
    start = getattr(row, "period_start", None)
    end = getattr(row, "period_end", None)
    if not start:
        start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    if not end:
        next_month = (datetime.now().replace(day=28) + timedelta(days=7)).replace(day=1)
        end = next_month.strftime("%Y-%m-%d")
    return str(start), str(end)


def days_left(end_date: str) -> Optional[int]:
    try:
        end = datetime.strptime(str(end_date)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return (end - datetime.now()).days + 1


def avg_task_minutes(db: Session, tenant_id: int, sample: int = 10) -> Optional[float]:
    """最近若干条成功任务的平均耗时（分钟），用于估算排队等待"""
    row = db.execute(
        text(f"""
            SELECT AVG(d) AS m FROM (
                SELECT (julianday(end_time) - julianday(start_time)) * 1440.0 AS d
                FROM task_executions
                WHERE tenant_id = :tid AND status = 'success'
                  AND start_time IS NOT NULL AND end_time IS NOT NULL
                ORDER BY end_time DESC
                LIMIT {int(sample)}
            )
            WHERE d IS NOT NULL AND d > 0 AND d < 720
        """),
        {"tid": tenant_id},
    ).fetchone()
    if row and row.m:
        return round(float(row.m), 1)
    return None


def queue_map(db: Session, tenant_id: int) -> dict:
    """返回 {task_id: (排队位次, 预计等待分钟)}，只统计本租户排队中的任务

    后端是单 Worker 串行执行，排队位次按创建时间排，
    预计等待 = 前面排队的任务数 × 近期成功任务平均耗时。
    """
    rows = db.execute(
        text("""
            SELECT id, created_at FROM task_executions
            WHERE tenant_id = :tid AND status = 'queued'
            ORDER BY created_at ASC, id ASC
        """),
        {"tid": tenant_id},
    ).fetchall()

    avg = avg_task_minutes(db, tenant_id)
    result = {}
    for idx, r in enumerate(rows):
        position = idx + 1
        # 等待时间 = 前面排队的任务数 × 平均耗时；队首没有前置任务，返回 None 由前端显示「即将开始」
        ahead = position - 1
        eta = round(avg * ahead) if (avg and ahead > 0) else None
        result[r.id] = (position, eta)
    return result


def task_hits(db: Session, task_id: int) -> int:
    """任务命中的线索数（采集写入的线索，去重）"""
    row = db.execute(
        text("""
            SELECT COUNT(DISTINCT contact_id) AS cnt FROM contact_interactions
            WHERE task_execution_id = :tid AND interaction_type = 'scraped'
        """),
        {"tid": task_id},
    ).fetchone()
    return row.cnt if row else 0


def task_hits_bulk(db: Session, task_ids: list) -> dict:
    if not task_ids:
        return {}
    ids_str = ",".join(str(int(i)) for i in task_ids)
    rows = db.execute(
        text(f"""
            SELECT task_execution_id AS tid, COUNT(DISTINCT contact_id) AS cnt
            FROM contact_interactions
            WHERE task_execution_id IN ({ids_str}) AND interaction_type = 'scraped'
            GROUP BY task_execution_id
        """)
    ).fetchall()
    return {r.tid: r.cnt for r in rows}


def duration_minutes(row) -> Optional[int]:
    """任务耗时（分钟）"""
    start, end = getattr(row, "start_time", None), getattr(row, "end_time", None)
    if not start or not end:
        return None
    try:
        delta = datetime.strptime(str(end)[:19], "%Y-%m-%d %H:%M:%S") - datetime.strptime(
            str(start)[:19], "%Y-%m-%d %H:%M:%S"
        )
        return int(delta.total_seconds() // 60)
    except (ValueError, TypeError):
        return None


def status_label(status: str) -> str:
    return {
        "pending": "待启动",
        "queued": "等待中",
        "running": "运行中",
        "success": "成功",
        "failed": "失败",
        "cancelled": "已停止",
    }.get(status, status)


def build_scrape_task_config(db: Session, business_line_id: int, limit: int) -> Tuple[str, int, int]:
    """拼装采集任务的 task_config，返回 (配置 JSON, 预计条数, 关键词数)

    采集深度、评论数、风控节奏都由平台决定，不开放给客户改。
    任务中心与新手引导共用这一段，避免两处各写一份导致口径漂移。
    """
    keywords = [
        r[0] for r in db.execute(
            text("SELECT keyword FROM keywords WHERE business_line_id = :bl AND status = 1 ORDER BY priority DESC"),
            {"bl": business_line_id},
        ).fetchall()
    ]
    if not keywords:
        raise HTTPException(status_code=400, detail="该项目没有启用中的关键词，先去项目详情添加")

    per_keyword = max(1, math.ceil(limit / len(keywords)))
    template = db.execute(
        text("SELECT id FROM prompt_templates WHERE business_line_id = :bl AND is_active = 1 LIMIT 1"),
        {"bl": business_line_id},
    ).fetchone()

    config = json.dumps({
        "keywords": keywords,
        "content_types": ["video"],
        "max_items_per_keyword": per_keyword,
        "max_comments_per_video": 20,
        "ai_filter_enabled": True,
        "ai_prompt_template_id": template[0] if template else None,
        "exclude_author": True,
    }, ensure_ascii=False)
    return config, len(keywords) * per_keyword, len(keywords)
