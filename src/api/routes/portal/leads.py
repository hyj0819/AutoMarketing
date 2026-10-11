"""线索池：多条件筛选、详情、状态流转、CSV 导出"""

import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user, require_role
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.lead import (
    LeadDetail,
    LeadEvidence,
    LeadItem,
    LeadListResult,
    LeadStatusUpdate,
    TimelineItem,
)
from src.core.database import get_db
from ._common import period_bounds

router = APIRouter()

ALLOWED_STATUS = {
    'pending', 'contacted', 'replied', 'engaged',
    'qualified', 'won', 'lost', 'invalid', 'snoozed',
}

STATUS_LABEL = {
    'pending': '待触达', 'contacted': '已触达', 'replied': '已回复', 'engaged': '有效对话',
    'qualified': '已确认需求', 'won': '已成交', 'lost': '已丢单', 'invalid': '误判', 'snoozed': '稍后联系',
}

BASE_SELECT = """
    SELECT c.id, c.username, c.platform_user_id, c.business_line_id, c.source_keyword,
           c.contact_status, c.owner, c.quote_amount, c.deal_amount, c.lost_reason,
           c.last_contact_at, c.created_at, c.metadata, c.notes,
           p.name AS platform_name, bl.name AS business_line_name
    FROM contacts c
    LEFT JOIN platforms p ON c.platform_id = p.id
    LEFT JOIN business_lines bl ON c.business_line_id = bl.id
"""


def _filters(ctx: TenantContext, status=None, platform_id=None, business_line_id=None,
             source_keyword=None, owner=None, q=None):
    conditions = ["c.tenant_id = :tid"]
    params: dict = {"tid": ctx.tenant_id}
    if status:
        conditions.append("c.contact_status = :st")
        params["st"] = status
    if platform_id:
        conditions.append("c.platform_id = :pid")
        params["pid"] = platform_id
    if business_line_id:
        conditions.append("c.business_line_id = :bl")
        params["bl"] = business_line_id
    if source_keyword:
        conditions.append("c.source_keyword = :kw")
        params["kw"] = source_keyword
    if owner:
        conditions.append("c.owner = :owner")
        params["owner"] = owner
    if q:
        conditions.append("(c.username LIKE :q OR c.platform_user_id LIKE :q OR c.metadata LIKE :q OR c.notes LIKE :q)")
        params["q"] = f"%{q}%"
    if ctx.visible_scope:
        ids = ",".join(str(i) for i in ctx.visible_scope)
        conditions.append(f"c.business_line_id IN ({ids})")
    return " AND ".join(conditions), params


def _build_item(r) -> LeadItem:
    comment = ''
    ai_level = '中'
    try:
        meta = json.loads(r.metadata or '{}')
        comment = meta.get('comment') or meta.get('content_text') or ''
        ai_level = str(meta.get('ai_level') or meta.get('intent_level') or '中')
    except (ValueError, TypeError):
        pass
    return LeadItem(
        id=r.id,
        username=r.username or r.platform_user_id,
        platform_name=getattr(r, "platform_name", None),
        business_line_name=getattr(r, "business_line_name", None),
        comment=(comment or '')[:140],
        source_keyword=r.source_keyword,
        ai_level=ai_level,
        status=r.contact_status,
        status_label=STATUS_LABEL.get(r.contact_status, r.contact_status),
        owner=r.owner,
        quote_amount=float(r.quote_amount) if r.quote_amount is not None else None,
        deal_amount=float(r.deal_amount) if r.deal_amount is not None else None,
        lost_reason=r.lost_reason,
        last_contact_at=str(r.last_contact_at) if r.last_contact_at else None,
        created_at=str(r.created_at),
    )


@router.get("/leads", response_model=ApiResponse[LeadListResult])
def list_leads(
    status: str = None,
    platform_id: int = None,
    business_line_id: int = None,
    source_keyword: str = None,
    owner: str = None,
    q: str = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """线索池列表，严格按租户隔离"""
    where, params = _filters(ctx, status, platform_id, business_line_id, source_keyword, owner, q)
    total = db.execute(
        text(f"SELECT COUNT(*) AS cnt FROM contacts c WHERE {where}"), params
    ).fetchone().cnt

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    rows = db.execute(
        text(f"{BASE_SELECT} WHERE {where} ORDER BY c.created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    ).fetchall()

    return ApiResponse(result=LeadListResult(
        items=[_build_item(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    ))


@router.get("/leads/export")
def export_leads(
    status: str = None,
    platform_id: int = None,
    business_line_id: int = None,
    source_keyword: str = None,
    owner: str = None,
    q: str = None,
    ctx: TenantContext = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """导出 CSV，范围跟随当前筛选条件"""
    where, params = _filters(ctx, status, platform_id, business_line_id, source_keyword, owner, q)
    rows = db.execute(
        text(f"{BASE_SELECT} WHERE {where} ORDER BY c.created_at DESC LIMIT 5000"),
        params,
    ).fetchall()

    output = io.StringIO()
    output.write('\ufeff')  # Excel 中文不乱码
    writer = csv.writer(output)
    writer.writerow(['线索ID', '用户名', '平台', '项目', '来源关键词', '状态', 'AI判断',
                     '负责人', '报价金额', '成交金额', '丢单原因', '最后联系时间', '创建时间'])
    for r in rows:
        item = _build_item(r)
        writer.writerow([
            item.id, item.username, item.platform_name, item.business_line_name,
            item.source_keyword, item.status_label, item.ai_level, item.owner,
            # 金额取整到元，表格软件里不会出现 10800.0 这种尾巴
            round(item.quote_amount) if item.quote_amount is not None else '',
            round(item.deal_amount) if item.deal_amount is not None else '',
            item.lost_reason or '', item.last_contact_at or '', item.created_at,
        ])
    output.seek(0)

    filename = f"leads-{ctx.tenant_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/leads/{lead_id}", response_model=ApiResponse[LeadDetail])
def get_lead(lead_id: int, ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """线索详情：证据区 + 上下文 + 跟进时间线"""
    row = db.execute(
        text(f"{BASE_SELECT} WHERE c.id = :id AND c.tenant_id = :tid"),
        {"id": lead_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="线索不存在")
    if ctx.visible_scope and row.business_line_id and row.business_line_id not in ctx.visible_scope:
        raise HTTPException(status_code=403, detail="该线索不在你的可见范围内")

    meta = {}
    try:
        meta = json.loads(row.metadata or '{}')
    except (ValueError, TypeError):
        meta = {}

    evidence = LeadEvidence(
        comment=meta.get('comment') or meta.get('content_text') or '',
        source_title=meta.get('source_title') or meta.get('title'),
        source_url=meta.get('source_url') or meta.get('content_url'),
        ai_conclusion=meta.get('ai_conclusion') or '',
        hit_reason=meta.get('hit_reason') or (('命中关键词：' + row.source_keyword) if row.source_keyword else ''),
    )

    context = {
        'platform': getattr(row, "platform_name", None),
        'business_line': getattr(row, "business_line_name", None),
        'source_keyword': row.source_keyword,
        'owner': row.owner,
        'quote_amount': float(row.quote_amount) if row.quote_amount is not None else None,
        'deal_amount': float(row.deal_amount) if row.deal_amount is not None else None,
        'lost_reason': row.lost_reason,
        'created_at': str(row.created_at),
        'last_contact_at': str(row.last_contact_at) if row.last_contact_at else None,
    }

    timeline = _timeline(db, lead_id)

    return ApiResponse(result=LeadDetail(
        lead=_build_item(row),
        evidence=evidence,
        context=context,
        timeline=timeline,
    ))


@router.post("/leads/{lead_id}/status", response_model=ApiResponse[LeadItem])
def update_lead_status(
    lead_id: int,
    data: LeadStatusUpdate,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """状态流转。丢单必须选原因，成交填金额"""
    if data.status not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="不支持的状态")
    if data.status == 'lost' and not data.reason:
        raise HTTPException(status_code=400, detail="丢单必须选择原因")

    row = db.execute(
        text("SELECT * FROM contacts WHERE id = :id AND tenant_id = :tid"),
        {"id": lead_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="线索不存在")
    if ctx.visible_scope and row.business_line_id and row.business_line_id not in ctx.visible_scope:
        raise HTTPException(status_code=403, detail="该线索不在你的可见范围内")

    from_status = row.contact_status
    deal_amount = _parse_amount(data.note) if data.status == 'won' else None

    db.execute(
        text("""
            UPDATE contacts
            SET contact_status = :st,
                lost_reason = CASE WHEN :st = 'lost' THEN :reason ELSE lost_reason END,
                deal_amount = COALESCE(:amount, deal_amount),
                won_at = CASE WHEN :st = 'won' THEN CURRENT_TIMESTAMP ELSE won_at END,
                replied_at = CASE WHEN :st IN ('replied', 'engaged', 'qualified', 'won', 'lost')
                                  THEN COALESCE(replied_at, CURRENT_TIMESTAMP) ELSE replied_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id AND tenant_id = :tid
        """),
        {
            "st": data.status,
            "reason": data.reason,
            "amount": deal_amount,
            "id": lead_id,
            "tid": ctx.tenant_id,
        },
    )
    db.execute(
        text("""
            INSERT INTO lead_status_logs (contact_id, from_status, to_status, reason, note, operator)
            VALUES (:cid, :from, :to, :reason, :note, :operator)
        """),
        {
            "cid": lead_id,
            "from": from_status,
            "to": data.status,
            "reason": data.reason,
            "note": data.note,
            "operator": ctx.real_name or ctx.email,
        },
    )
    db.commit()

    updated = db.execute(
        text(f"{BASE_SELECT} WHERE c.id = :id"), {"id": lead_id}
    ).fetchone()
    return ApiResponse(result=_build_item(updated))


# ---------------- 内部函数 ----------------

def _parse_amount(note: Optional[str]):
    """成交备注里形如「金额 12800」时提取金额；解析不出返回 None"""
    if not note:
        return None
    import re

    m = re.search(r'(\d+(?:\.\d+)?)', note.replace(',', ''))
    return float(m.group(1)) if m else None


def _timeline(db: Session, lead_id: int) -> list:
    rows = db.execute(
        text("""
            SELECT t, actor, title, detail, created_at FROM (
                SELECT 'scraped' AS t, '系统' AS actor, '采集到该线索' AS title,
                       COALESCE(detail, '') AS detail, created_at
                FROM contact_interactions WHERE contact_id = :id

                UNION ALL
                SELECT 'message' AS t, '系统' AS actor, '已发出私信' AS title,
                       COALESCE(detail, '') AS detail, created_at
                FROM contact_interactions WHERE contact_id = :id AND interaction_type = 'message_sent'

                UNION ALL
                SELECT 'status' AS t, COALESCE(operator, '成员') AS actor,
                       '状态变更为 ' || COALESCE(to_status, '') AS title,
                       COALESCE(reason, note, '') AS detail, created_at
                FROM lead_status_logs WHERE contact_id = :id
            )
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"id": lead_id},
    ).fetchall()

    items = []
    for r in rows:
        detail = (r.detail or '')
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                detail = parsed.get('message') or parsed.get('comment') or ''
        except (ValueError, TypeError):
            pass
        items.append(TimelineItem(
            time=str(r.created_at)[:16],
            title=r.title,
            actor=r.actor or '系统',
            detail=detail[:200] or None,
        ))
    return items
