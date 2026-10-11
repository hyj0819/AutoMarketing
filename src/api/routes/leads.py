"""
线索跟进路由

跟进工作台的后端支撑：待办聚合、线索队列、线索详情、状态流转、成交登记。
与 contacts 路由读写同一张 contacts 表，contacts 路由保持可用，不破坏既有调用。
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from datetime import datetime
import io
import csv
import json

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.contact import ContactInteractionResponse
from src.api.schemas.lead import (
    LeadResponse, LeadStatusUpdate, LeadQuoteCreate, LeadDealCreate,
    LeadBatchRequest, LeadBucket, LeadTodoStats, LeadTodoResponse,
    LeadStatusLog, LEAD_STATUSES, LOST_REASONS,
)
from src.api.routes.auth import get_current_user

router = APIRouter()

# 处于「跟进中」的状态
FOLLOWING_STATUSES = ('replied', 'engaged', 'qualified')

BASE_SELECT = """
    SELECT c.*, p.name as platform_name, bl.name as business_line_name
    FROM contacts c
    LEFT JOIN platforms p ON c.platform_id = p.id
    LEFT JOIN business_lines bl ON c.business_line_id = bl.id
"""


def _parse_metadata(metadata: Optional[str]) -> dict:
    """解析 metadata JSON，失败时返回空字典"""
    if not metadata:
        return {}
    try:
        data = json.loads(metadata)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _row_to_lead(row) -> LeadResponse:
    """数据库行转 LeadResponse，同时把 metadata 里的证据字段提到顶层"""
    meta = _parse_metadata(getattr(row, 'metadata', None))
    return LeadResponse(
        id=row.id,
        platform_id=row.platform_id,
        platform_name=getattr(row, 'platform_name', None),
        business_line_id=row.business_line_id,
        business_line_name=getattr(row, 'business_line_name', None),
        platform_user_id=row.platform_user_id,
        username=row.username,
        profile_url=row.profile_url,
        is_author=row.is_author or 0,
        contact_status=row.contact_status,
        contact_attempts=row.contact_attempts or 0,
        last_contact_at=str(row.last_contact_at) if row.last_contact_at else None,
        replied_at=str(row.replied_at) if row.replied_at else None,
        quote_amount=row.quote_amount,
        quoted_at=str(row.quoted_at) if row.quoted_at else None,
        deal_amount=row.deal_amount,
        won_at=str(row.won_at) if row.won_at else None,
        lost_reason=row.lost_reason,
        owner=row.owner,
        snooze_until=str(row.snooze_until) if row.snooze_until else None,
        tags=row.tags,
        notes=row.notes,
        metadata=row.metadata,
        comment=meta.get('comment'),
        source_title=meta.get('source_title'),
        source_video=meta.get('source_video'),
        source_keyword=meta.get('source_keyword'),
        created_at=str(row.created_at) if row.created_at else None,
        updated_at=str(row.updated_at) if row.updated_at else None,
    )


def _build_conditions(
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    contact_status: Optional[str] = None,
    owner: Optional[str] = None,
    keyword: Optional[str] = None,
    source_keyword: Optional[str] = None,
) -> tuple:
    """构造筛选条件，返回 (where_clause, params)"""
    conditions = []
    params = {}

    if platform_id:
        conditions.append("c.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if business_line_id:
        conditions.append("c.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if contact_status:
        # 支持逗号分隔的多状态
        status_list = [s.strip() for s in contact_status.split(',') if s.strip()]
        if status_list:
            placeholders = ", ".join([f":st_{i}" for i in range(len(status_list))])
            conditions.append(f"c.contact_status IN ({placeholders})")
            for i, s in enumerate(status_list):
                params[f"st_{i}"] = s
    if owner:
        conditions.append("c.owner = :owner")
        params["owner"] = owner
    if keyword:
        conditions.append(
            "(c.username LIKE :keyword OR c.platform_user_id LIKE :keyword OR c.metadata LIKE :keyword)"
        )
        params["keyword"] = f"%{keyword}%"
    if source_keyword:
        conditions.append("c.metadata LIKE :source_keyword")
        params["source_keyword"] = f"%{source_keyword}%"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where_clause, params


def _write_status_log(
    db: Session,
    contact_id: int,
    from_status: str,
    to_status: str,
    reason: Optional[str],
    note: Optional[str],
    operator: Optional[str],
) -> None:
    """写状态流转记录，同时在触达历史里留一条，保证时间线完整"""
    db.execute(text("""
        INSERT INTO lead_status_logs (contact_id, from_status, to_status, reason, note, operator)
        VALUES (:contact_id, :from_status, :to_status, :reason, :note, :operator)
    """), {
        "contact_id": contact_id,
        "from_status": from_status,
        "to_status": to_status,
        "reason": reason,
        "note": note,
        "operator": operator,
    })

    detail_parts = [f"{LEAD_STATUSES.get(from_status, from_status)} 变更为 {LEAD_STATUSES.get(to_status, to_status)}"]
    if reason:
        detail_parts.append(f"原因：{LOST_REASONS.get(reason, reason)}")
    if note:
        detail_parts.append(f"备注：{note}")
    db.execute(text("""
        INSERT INTO contact_interactions (contact_id, interaction_type, detail)
        VALUES (:contact_id, 'status_change', :detail)
    """), {"contact_id": contact_id, "detail": "，".join(detail_parts)})


# ==================== 待办聚合 ====================

@router.get("/todo", response_model=ApiResponse[dict])
def get_lead_todo(db: Session = Depends(get_db)):
    """今日待办：四个数字卡加四个待办队列"""
    # 今日新回复
    new_reply_sql = text(f"""
        {BASE_SELECT}
        WHERE c.contact_status = 'replied'
          AND date(COALESCE(c.replied_at, c.updated_at)) >= date('now')
        ORDER BY COALESCE(c.replied_at, c.updated_at) DESC
        LIMIT 20
    """)
    # 超过 24 小时未跟进
    overdue_sql = text(f"""
        {BASE_SELECT}
        WHERE c.contact_status = 'replied'
          AND COALESCE(c.replied_at, c.updated_at) < datetime('now', '-24 hours')
        ORDER BY COALESCE(c.replied_at, c.updated_at) ASC
        LIMIT 20
    """)
    # 稍后联系到期
    snoozed_sql = text(f"""
        {BASE_SELECT}
        WHERE c.contact_status = 'snoozed'
          AND (c.snooze_until IS NULL OR c.snooze_until <= datetime('now'))
        ORDER BY c.snooze_until ASC
        LIMIT 20
    """)
    # 已报价超过 3 天没动静
    stale_sql = text(f"""
        {BASE_SELECT}
        WHERE c.contact_status = 'qualified'
          AND c.quote_amount IS NOT NULL
          AND COALESCE(c.quoted_at, c.updated_at) < datetime('now', '-3 days')
        ORDER BY COALESCE(c.quoted_at, c.updated_at) ASC
        LIMIT 20
    """)

    new_replies = [_row_to_lead(r) for r in db.execute(new_reply_sql).fetchall()]
    overdue = [_row_to_lead(r) for r in db.execute(overdue_sql).fetchall()]
    snoozed = [_row_to_lead(r) for r in db.execute(snoozed_sql).fetchall()]
    stale = [_row_to_lead(r) for r in db.execute(stale_sql).fetchall()]

    def count_where(clause: str, params: dict = None) -> int:
        sql = text(f"SELECT COUNT(*) FROM contacts c WHERE {clause}")
        return db.execute(sql, params or {}).fetchone()[0]

    new_replies_count = count_where(
        "c.contact_status = 'replied' AND date(COALESCE(c.replied_at, c.updated_at)) >= date('now')"
    )
    overdue_count = count_where(
        "c.contact_status = 'replied' AND COALESCE(c.replied_at, c.updated_at) < datetime('now', '-24 hours')"
    )
    following_count = count_where(
        "c.contact_status IN ('replied', 'engaged', 'qualified')"
    )

    won_row = db.execute(text("""
        SELECT COUNT(*), COALESCE(SUM(deal_amount), 0)
        FROM contacts
        WHERE contact_status = 'won' AND COALESCE(won_at, updated_at) >= datetime('now', '-7 days')
    """)).fetchone()

    stats = LeadTodoStats(
        new_replies=new_replies_count,
        pending_follow=overdue_count,
        following=following_count,
        won_this_week=won_row[0] or 0,
        won_amount_this_week=float(won_row[1] or 0),
    )

    buckets = [
        LeadBucket(key="new_replies", title="今日新回复", count=new_replies_count, list=new_replies),
        LeadBucket(key="overdue", title="超过 24 小时未跟进", count=overdue_count, list=overdue),
        LeadBucket(key="snoozed", title="今天该回访", count=len(snoozed), list=snoozed),
        LeadBucket(key="stale", title="报价后 3 天没动静", count=len(stale), list=stale),
    ]

    return ApiResponse(result=LeadTodoResponse(
        stats=stats,
        buckets=[b.model_dump() for b in buckets],
    ).model_dump())


# ==================== 负责人列表 ====================

@router.get("/owners", response_model=ApiResponse[List[str]])
def list_owners(db: Session = Depends(get_db)):
    """获取已有的负责人列表"""
    rows = db.execute(text(
        "SELECT DISTINCT owner FROM contacts WHERE owner IS NOT NULL AND owner != '' ORDER BY owner"
    )).fetchall()
    return ApiResponse(result=[r[0] for r in rows])


# ==================== 线索队列 ====================

@router.get("/", response_model=ApiResponse[dict])
def list_leads(
    page: int = 1,
    pageSize: int = 20,
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    contact_status: Optional[str] = None,
    owner: Optional[str] = None,
    keyword: Optional[str] = None,
    source_keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """线索队列，按「该做什么」排序：跟进中的排前面，越久没动排越前"""
    where_clause, params = _build_conditions(
        platform_id, business_line_id, contact_status, owner, keyword, source_keyword
    )

    total = db.execute(
        text(f"SELECT COUNT(*) FROM contacts c {where_clause}"), params
    ).fetchone()[0]

    offset = (page - 1) * pageSize
    params["limit"] = pageSize
    params["offset"] = offset

    rows = db.execute(text(f"""
        {BASE_SELECT}
        {where_clause}
        ORDER BY
            CASE c.contact_status
                WHEN 'replied' THEN 0
                WHEN 'engaged' THEN 1
                WHEN 'qualified' THEN 2
                WHEN 'snoozed' THEN 3
                WHEN 'contacted' THEN 4
                WHEN 'pending' THEN 5
                ELSE 6
            END,
            COALESCE(c.last_contact_at, c.created_at) ASC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    return ApiResponse(result={
        "list": [_row_to_lead(r).model_dump() for r in rows],
        "pageCount": (total + pageSize - 1) // pageSize if total > 0 else 0,
        "itemCount": total,
    })


# ==================== 导出 ====================

@router.get("/export")
def export_leads(
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    contact_status: Optional[str] = None,
    owner: Optional[str] = None,
    keyword: Optional[str] = None,
    source_keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """导出线索为 CSV，含成交金额与丢单原因"""
    where_clause, params = _build_conditions(
        platform_id, business_line_id, contact_status, owner, keyword, source_keyword
    )
    rows = db.execute(text(f"""
        {BASE_SELECT}
        {where_clause}
        ORDER BY c.created_at DESC
    """), params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', '平台', '项目', '用户名', '平台用户ID', '状态', '来源关键词',
        '负责人', '报价金额', '成交金额', '丢单原因', '触达次数', '最后触达', '创建时间'
    ])
    for row in rows:
        lead = _row_to_lead(row)
        writer.writerow([
            lead.id,
            lead.platform_name or '',
            lead.business_line_name or '',
            lead.username or '',
            lead.platform_user_id,
            LEAD_STATUSES.get(lead.contact_status, lead.contact_status),
            lead.source_keyword or '',
            lead.owner or '',
            lead.quote_amount if lead.quote_amount is not None else '',
            lead.deal_amount if lead.deal_amount is not None else '',
            LOST_REASONS.get(lead.lost_reason, lead.lost_reason) if lead.lost_reason else '',
            lead.contact_attempts,
            lead.last_contact_at or '',
            lead.created_at or '',
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"}
    )


# ==================== 批量操作 ====================

@router.post("/batch", response_model=ApiResponse[dict])
def batch_update_leads(
    data: LeadBatchRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """批量改状态、指派负责人、打标签"""
    if not data.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    updated = 0
    for contact_id in data.ids:
        row = db.execute(
            text("SELECT id, contact_status FROM contacts WHERE id = :id"), {"id": contact_id}
        ).fetchone()
        if not row:
            continue

        if data.action == 'status':
            to_status = data.value or ''
            if to_status not in LEAD_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid status: {to_status}")
            if to_status == 'lost' and data.reason not in LOST_REASONS:
                raise HTTPException(status_code=400, detail="丢单必须选择原因")
            _write_status_log(db, contact_id, row.contact_status, to_status,
                              data.reason, None, current_user["username"])
            extra = ""
            if to_status == 'lost':
                extra = ", lost_reason = :lost_reason"
            elif to_status == 'won':
                extra = ", won_at = CURRENT_TIMESTAMP, lost_reason = NULL"
            elif to_status == 'replied':
                extra = ", replied_at = CURRENT_TIMESTAMP"
            params = {"id": contact_id, "status": to_status}
            if to_status == 'lost':
                params["lost_reason"] = data.reason
            db.execute(text(f"""
                UPDATE contacts SET contact_status = :status, updated_at = CURRENT_TIMESTAMP{extra}
                WHERE id = :id
            """), params)
            updated += 1

        elif data.action == 'owner':
            db.execute(text(
                "UPDATE contacts SET owner = :owner, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ), {"id": contact_id, "owner": data.value or None})
            updated += 1

        elif data.action == 'tags':
            tags_value = data.value or ''
            tag_list = [t.strip() for t in tags_value.split(',') if t.strip()]
            db.execute(text(
                "UPDATE contacts SET tags = :tags, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ), {"id": contact_id, "tags": json.dumps(tag_list, ensure_ascii=False)})
            updated += 1

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action: {data.action}")

    db.commit()
    return ApiResponse(result={"updated_count": updated})


# ==================== 线索详情 ====================

@router.get("/{lead_id}", response_model=ApiResponse[dict])
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """线索详情：基本信息加证据字段、触达历史、状态流转记录"""
    row = db.execute(
        text(f"{BASE_SELECT} WHERE c.id = :id"), {"id": lead_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    interactions = db.execute(text("""
        SELECT * FROM contact_interactions WHERE contact_id = :cid ORDER BY created_at DESC
    """), {"cid": lead_id}).fetchall()

    logs = db.execute(text("""
        SELECT * FROM lead_status_logs WHERE contact_id = :cid ORDER BY created_at DESC
    """), {"cid": lead_id}).fetchall()

    return ApiResponse(result={
        "lead": _row_to_lead(row).model_dump(),
        "interactions": [
            ContactInteractionResponse(
                id=r.id,
                contact_id=r.contact_id,
                interaction_type=r.interaction_type,
                task_execution_id=r.task_execution_id,
                detail=r.detail,
                created_at=str(r.created_at),
            ).model_dump() for r in interactions
        ],
        "status_logs": [
            LeadStatusLog(
                id=r.id,
                contact_id=r.contact_id,
                from_status=r.from_status,
                to_status=r.to_status,
                reason=r.reason,
                note=r.note,
                operator=r.operator,
                created_at=str(r.created_at),
            ).model_dump() for r in logs
        ],
    })


# ==================== 状态流转 ====================

@router.post("/{lead_id}/status", response_model=ApiResponse[dict])
def update_lead_status(
    lead_id: int,
    data: LeadStatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """流转线索状态"""
    row = db.execute(
        text("SELECT id, contact_status FROM contacts WHERE id = :id"), {"id": lead_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    to_status = data.to_status
    if to_status not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {to_status}")
    if to_status == 'lost' and data.reason not in LOST_REASONS:
        raise HTTPException(status_code=400, detail="丢单必须选择原因")

    from_status = row.contact_status
    _write_status_log(db, lead_id, from_status, to_status, data.reason, data.note,
                      current_user["username"])

    sets = ["contact_status = :status", "updated_at = CURRENT_TIMESTAMP"]
    params = {"id": lead_id, "status": to_status}

    if to_status == 'replied':
        sets.append("replied_at = CURRENT_TIMESTAMP")
    if to_status == 'lost':
        sets.append("lost_reason = :lost_reason")
        params["lost_reason"] = data.reason
    if to_status == 'won':
        sets.append("won_at = CURRENT_TIMESTAMP")
        sets.append("lost_reason = NULL")
    if to_status == 'snoozed':
        sets.append("snooze_until = :snooze_until")
        params["snooze_until"] = data.snooze_until or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if data.note:
        sets.append("notes = :notes")
        params["notes"] = data.note

    db.execute(text(f"UPDATE contacts SET {', '.join(sets)} WHERE id = :id"), params)
    db.commit()

    new_row = db.execute(
        text(f"{BASE_SELECT} WHERE c.id = :id"), {"id": lead_id}
    ).fetchone()
    return ApiResponse(result=_row_to_lead(new_row).model_dump())


# ==================== 登记报价 ====================

@router.post("/{lead_id}/quote", response_model=ApiResponse[dict])
def update_lead_quote(
    lead_id: int,
    data: LeadQuoteCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """登记报价金额"""
    row = db.execute(
        text("SELECT id FROM contacts WHERE id = :id"), {"id": lead_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    db.execute(text("""
        UPDATE contacts
        SET quote_amount = :amount, quoted_at = CURRENT_TIMESTAMP,
            contact_status = CASE WHEN contact_status IN ('pending','contacted','replied','engaged')
                                  THEN 'qualified' ELSE contact_status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
    """), {"id": lead_id, "amount": data.quote_amount})

    db.execute(text("""
        INSERT INTO contact_interactions (contact_id, interaction_type, detail)
        VALUES (:cid, 'quote', :detail)
    """), {"cid": lead_id, "detail": f"登记报价 {data.quote_amount}" + (f"，备注：{data.note}" if data.note else "")})
    db.commit()

    new_row = db.execute(text(f"{BASE_SELECT} WHERE c.id = :id"), {"id": lead_id}).fetchone()
    return ApiResponse(result=_row_to_lead(new_row).model_dump())


# ==================== 登记成交 ====================

@router.post("/{lead_id}/deal", response_model=ApiResponse[dict])
def register_lead_deal(
    lead_id: int,
    data: LeadDealCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """登记成交，状态自动置为 won"""
    row = db.execute(
        text("SELECT id, contact_status FROM contacts WHERE id = :id"), {"id": lead_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    _write_status_log(db, lead_id, row.contact_status, 'won', None, data.note,
                      current_user["username"])

    db.execute(text("""
        UPDATE contacts
        SET contact_status = 'won', deal_amount = :amount, won_at = CURRENT_TIMESTAMP,
            lost_reason = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
    """), {"id": lead_id, "amount": data.deal_amount})

    detail = f"成交金额 {data.deal_amount}" + (f"，产品：{data.product}" if data.product else "")
    if data.note:
        detail += f"，备注：{data.note}"
    db.execute(text("""
        INSERT INTO contact_interactions (contact_id, interaction_type, detail)
        VALUES (:cid, 'deal_won', :detail)
    """), {"cid": lead_id, "detail": detail})
    db.commit()

    new_row = db.execute(text(f"{BASE_SELECT} WHERE c.id = :id"), {"id": lead_id}).fetchone()
    return ApiResponse(result=_row_to_lead(new_row).model_dump())
