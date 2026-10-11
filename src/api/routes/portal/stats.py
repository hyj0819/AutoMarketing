"""数据看板：转化漏斗、趋势（日/周/月）、关键词归因、话术效果对比"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.stats import (
    AttributionItem,
    FunnelResult,
    FunnelStage,
    ScriptEffectItem,
    TrendPoint,
    TrendResult,
)
from src.core.database import get_db
from ._common import REACHED_IN_SQL, period_bounds

router = APIRouter()

REPLIED_STATUSES = "'replied', 'engaged', 'qualified', 'won', 'lost'"
LOST_REASON_LABEL = {
    'price': '价格',
    'no_need': '暂时不需要',
    'bought_other': '已买别家',
    'no_response': '无回应',
    'mistake': '误判',
}


@router.get("/stats/funnel", response_model=ApiResponse[FunnelResult])
def get_funnel(ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """转化漏斗：采集 → 筛选 → 触达 → 回复 → 成交

    最后两级的原料是跟进工作台登记过的成交金额与丢单原因，没登记就是空的。
    """
    tenant = db.execute(text("SELECT * FROM tenants WHERE id = :tid"), {"tid": ctx.tenant_id}).fetchone()
    start, end = period_bounds(tenant) if tenant else ("1970-01-01", "2999-12-31")

    row = db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM contents WHERE tenant_id = :tid AND date(scraped_at) >= :start) AS collected,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) >= :start) AS leads,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) >= :start
                    AND contact_status IN ({reached})) AS reached,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) >= :start
                    AND contact_status IN ({replied})) AS replied,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) >= :start
                    AND contact_status = 'won') AS won,
                (SELECT COALESCE(SUM(deal_amount), 0) FROM contacts WHERE tenant_id = :tid
                    AND date(created_at) >= :start AND contact_status = 'won') AS amount,
                (SELECT COUNT(*) FROM contacts WHERE tenant_id = :tid AND date(created_at) >= :start
                    AND contact_status = 'lost') AS lost
        """.format(reached=REACHED_IN_SQL, replied=REPLIED_STATUSES)),
        {"tid": ctx.tenant_id, "start": start},
    ).fetchone()

    values = [
        ("collected", "采集内容", int(row.collected or 0)),
        ("leads", "筛选通过", int(row.leads or 0)),
        ("reached", "已触达", int(row.reached or 0)),
        ("replied", "已回复", int(row.replied or 0)),
        ("won", "成交", int(row.won or 0)),
    ]

    stages, prev = [], None
    for key, title, count in values:
        rate = None
        if prev is not None:
            rate = round(count / prev * 100, 1) if prev else 0.0
        stages.append(FunnelStage(key=key, title=title, count=count, rate=rate))
        prev = count

    lost_rows = db.execute(
        text("""
            SELECT lost_reason, COUNT(*) AS cnt FROM contacts
            WHERE tenant_id = :tid AND contact_status = 'lost' AND date(created_at) >= :start
            GROUP BY lost_reason ORDER BY cnt DESC
        """),
        {"tid": ctx.tenant_id, "start": start},
    ).fetchall()
    lost_reasons = [
        {"reason": LOST_REASON_LABEL.get(r.lost_reason, r.lost_reason or '未填'), "count": int(r.cnt or 0)}
        for r in lost_rows
    ]

    won_count = int(row.won or 0)
    amount = float(row.amount or 0)
    return ApiResponse(result=FunnelResult(
        stages=stages,
        won_amount=amount,
        # 客单价取整到元，避免看板上出现 ¥12,342.86 这种零头
        avg_deal_amount=round(amount / won_count) if won_count else 0.0,
        won_count=won_count,
        lost_count=int(row.lost or 0),
        lost_reasons=lost_reasons,
    ))


@router.get("/stats/trend", response_model=ApiResponse[TrendResult])
def get_trend(
    granularity: str = 'day',
    ctx: TenantContext = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """趋势：日（近 14 天）、周（近 8 周）、月（近 6 个月）"""
    granularity = granularity if granularity in ('day', 'week', 'month') else 'day'

    if granularity == 'month':
        points = _monthly_points(db, ctx.tenant_id, months=6)
    else:
        points = _daily_buckets(db, ctx.tenant_id, granularity)

    return ApiResponse(result=TrendResult(granularity=granularity, points=points))


@router.get("/stats/attribution", response_model=ApiResponse[list])
def get_attribution(ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """关键词归因排行：哪个词带来的线索、回复与成交最多"""
    rows = db.execute(
        text("""
            SELECT source_keyword AS keyword,
                   COUNT(*) AS leads,
                   SUM(CASE WHEN contact_status IN ({replied}) THEN 1 ELSE 0 END) AS replies,
                   SUM(CASE WHEN contact_status = 'won' THEN 1 ELSE 0 END) AS won,
                   SUM(CASE WHEN contact_status = 'won' THEN COALESCE(deal_amount, 0) ELSE 0 END) AS amount
            FROM contacts
            WHERE tenant_id = :tid AND source_keyword IS NOT NULL AND source_keyword != ''
            GROUP BY source_keyword
            ORDER BY leads DESC
            LIMIT 10
        """.format(replied=REPLIED_STATUSES)),
        {"tid": ctx.tenant_id},
    ).fetchall()

    return ApiResponse(result=[
        AttributionItem(
            keyword=r.keyword,
            leads=int(r.leads or 0),
            replies=int(r.replies or 0),
            won=int(r.won or 0),
            amount=float(r.amount or 0),
        )
        for r in rows
    ])


@router.get("/stats/scripts", response_model=ApiResponse[list])
def get_script_effects(ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """话术效果对比：按话术模板名聚合触达与回复，算回复率

    按模板名聚合，跨项目复制的同名模板会合并统计，便于横向比较。
    """
    rows = db.execute(
        text("""
            SELECT pt.name AS name,
                   SUM(CASE WHEN c.contact_status IN ({reached}) THEN 1 ELSE 0 END) AS reach,
                   SUM(CASE WHEN c.contact_status IN ({replied}) THEN 1 ELSE 0 END) AS replies,
                   MAX(pt.is_active) AS is_active
            FROM contacts c
            JOIN prompt_templates pt ON c.prompt_template_id = pt.id
            WHERE c.tenant_id = :tid
            GROUP BY pt.name
            ORDER BY reach DESC
        """.format(reached=REACHED_IN_SQL, replied=REPLIED_STATUSES)),
        {"tid": ctx.tenant_id},
    ).fetchall()

    return ApiResponse(result=[
        ScriptEffectItem(
            name=r.name,
            reach=int(r.reach or 0),
            replies=int(r.replies or 0),
            reply_rate=round(int(r.replies or 0) / int(r.reach or 0) * 100, 1) if r.reach else 0.0,
            is_active=int(r.is_active or 0),
        )
        for r in rows
    ])


# ---------------- 内部函数 ----------------

def _daily_counts(db: Session, tenant_id: int, days: int, date_col: str) -> dict:
    rows = db.execute(
        text(f"""
            SELECT date({date_col}) AS d, COUNT(*) AS c
            FROM contacts
            WHERE tenant_id = :tid AND {date_col} IS NOT NULL
              AND date({date_col}) >= date('now', :off)
            GROUP BY date({date_col})
        """),
        {"tid": tenant_id, "off": f"-{days - 1} days"},
    ).fetchall()
    return {str(r.d): int(r.c or 0) for r in rows}


def _daily_buckets(db: Session, tenant_id: int, granularity: str) -> list:
    if granularity == 'day':
        days, size, count = 14, 1, 14
    else:
        days, size, count = 56, 7, 8

    leads = _daily_counts(db, tenant_id, days, 'created_at')
    reach = _daily_counts(db, tenant_id, days, 'last_contact_at')

    today = datetime.now().date()
    points = []
    for i in range(count - 1, -1, -1):
        end_day = today - timedelta(days=i * size)
        start_day = end_day - timedelta(days=size - 1)
        label = end_day.strftime('%m-%d')
        if granularity == 'week':
            label = f"{start_day.strftime('%m-%d')}~{end_day.strftime('%m-%d')}"
        l = sum(v for d, v in leads.items() if start_day <= _parse_date(d) <= end_day)
        r = sum(v for d, v in reach.items() if start_day <= _parse_date(d) <= end_day)
        points.append(TrendPoint(label=label, leads=l, reach=r))
    return points


def _monthly_points(db: Session, tenant_id: int, months: int = 6) -> list:
    rows = db.execute(
        text("""
            SELECT strftime('%Y-%m', created_at) AS m, COUNT(*) AS c
            FROM contacts WHERE tenant_id = :tid AND created_at IS NOT NULL
            GROUP BY strftime('%Y-%m', created_at)
        """),
        {"tid": tenant_id},
    ).fetchall()
    leads = {str(r.m): int(r.c or 0) for r in rows}

    rows = db.execute(
        text("""
            SELECT strftime('%Y-%m', last_contact_at) AS m, COUNT(*) AS c
            FROM contacts
            WHERE tenant_id = :tid AND last_contact_at IS NOT NULL AND contact_status IN ({reached})
            GROUP BY strftime('%Y-%m', last_contact_at)
        """.format(reached=REACHED_IN_SQL)),
        {"tid": tenant_id},
    ).fetchall()
    reach = {str(r.m): int(r.c or 0) for r in rows}

    now = datetime.now()
    points = []
    for i in range(months - 1, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        key = f"{year}-{month:02d}"
        points.append(TrendPoint(label=f"{month}月", leads=leads.get(key, 0), reach=reach.get(key, 0)))
    return points


def _parse_date(value: str):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return datetime.now().date()
