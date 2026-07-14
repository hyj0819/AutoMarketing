"""
触达用户管理路由
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
import io
import csv

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.contact import (
    ContactCreate, ContactUpdate, ContactResponse,
    ContactInteractionCreate, ContactInteractionResponse,
    BatchUpdateRequest
)

router = APIRouter()


def _build_contact(row) -> ContactResponse:
    """从数据库行构建 ContactResponse"""
    return ContactResponse(
        id=row.id,
        platform_id=row.platform_id,
        platform_name=getattr(row, 'platform_name', None),
        business_line_id=row.business_line_id,
        business_line_name=getattr(row, 'business_line_name', None),
        platform_user_id=row.platform_user_id,
        username=row.username,
        profile_url=row.profile_url,
        is_author=row.is_author,
        contact_status=row.contact_status,
        contact_attempts=row.contact_attempts,
        last_contact_at=str(row.last_contact_at) if row.last_contact_at else None,
        notes=row.notes,
        metadata=row.metadata,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at)
    )


@router.get("/", response_model=ApiResponse[dict])
def list_contacts(
    page: int = 1,
    pageSize: int = 10,
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    contact_status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取触达用户列表（分页+筛选+搜索）"""
    conditions = []
    params = {}

    if platform_id:
        conditions.append("c.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if business_line_id:
        conditions.append("c.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if contact_status:
        conditions.append("c.contact_status = :contact_status")
        params["contact_status"] = contact_status
    if keyword:
        conditions.append("(c.username LIKE :keyword OR c.platform_user_id LIKE :keyword)")
        params["keyword"] = f"%{keyword}%"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    # 查询总数
    count_sql = text(f"""
        SELECT COUNT(*) as total
        FROM contacts c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        {where_clause}
    """)
    total = db.execute(count_sql, params).fetchone()[0]

    # 分页查询
    offset = (page - 1) * pageSize
    query_sql = text(f"""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contacts c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        {where_clause}
        ORDER BY c.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    params["limit"] = pageSize
    params["offset"] = offset
    rows = db.execute(query_sql, params).fetchall()

    contacts = [_build_contact(row) for row in rows]

    return ApiResponse(result={
        "list": [c.model_dump() for c in contacts],
        "pageCount": (total + pageSize - 1) // pageSize if total > 0 else 0,
        "itemCount": total,
    })


@router.get("/export")
def export_contacts(
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    contact_status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """导出触达用户数据为CSV"""
    conditions = []
    params = {}

    if platform_id:
        conditions.append("c.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if business_line_id:
        conditions.append("c.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if contact_status:
        conditions.append("c.contact_status = :contact_status")
        params["contact_status"] = contact_status
    if keyword:
        conditions.append("(c.username LIKE :keyword OR c.platform_user_id LIKE :keyword)")
        params["keyword"] = f"%{keyword}%"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    query_sql = text(f"""
        SELECT c.id, p.name as platform_name, bl.name as business_line_name,
               c.platform_user_id, c.username, c.is_author, c.contact_status,
               c.contact_attempts, c.last_contact_at, c.notes, c.created_at
        FROM contacts c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        {where_clause}
        ORDER BY c.created_at DESC
    """)
    rows = db.execute(query_sql, params).fetchall()

    # 生成 CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', '平台', '业务线', '平台用户ID', '用户名', '是否作者',
        '触达状态', '触达次数', '最后触达时间', '备注', '创建时间'
    ])

    status_map = {'pending': '未触达', 'contacted': '已触达', 'replied': '已回复', 'converted': '已转化'}
    for row in rows:
        writer.writerow([
            row.id,
            row.platform_name or '',
            row.business_line_name or '',
            row.platform_user_id,
            row.username or '',
            '是' if row.is_author else '否',
            status_map.get(row.contact_status, row.contact_status),
            row.contact_attempts,
            str(row.last_contact_at) if row.last_contact_at else '',
            row.notes or '',
            str(row.created_at),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts_export.csv"}
    )


@router.post("/batch-update", response_model=ApiResponse[dict])
def batch_update_contacts(data: BatchUpdateRequest, db: Session = Depends(get_db)):
    """批量更新触达状态"""
    if not data.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    valid_statuses = ['pending', 'contacted', 'replied', 'converted']
    if data.contact_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    placeholders = ", ".join([f":id_{i}" for i in range(len(data.ids))])
    params = {f"id_{i}": id_val for i, id_val in enumerate(data.ids)}
    params["status"] = data.contact_status

    sql = text(f"""
        UPDATE contacts SET contact_status = :status, updated_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders})
    """)
    result = db.execute(sql, params)
    db.commit()

    return ApiResponse(result={"updated_count": result.rowcount})


@router.get("/{contact_id}", response_model=ApiResponse[dict])
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    """获取单个触达用户"""
    query = text("""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contacts c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        WHERE c.id = :id
    """)
    row = db.execute(query, {"id": contact_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    return ApiResponse(result=_build_contact(row).model_dump())


@router.post("/", response_model=ApiResponse[dict])
def create_contact(data: ContactCreate, db: Session = Depends(get_db)):
    """创建触达用户"""
    # 验证平台
    if not db.execute(text("SELECT * FROM platforms WHERE id = :id"), {"id": data.platform_id}).fetchone():
        raise HTTPException(status_code=404, detail="Platform not found")

    # 验证业务线
    if not db.execute(text("SELECT * FROM business_lines WHERE id = :id"), {"id": data.business_line_id}).fetchone():
        raise HTTPException(status_code=404, detail="Business line not found")

    try:
        query = text("""
            INSERT INTO contacts (platform_id, business_line_id, platform_user_id, username, profile_url, is_author, contact_status, notes, metadata)
            VALUES (:platform_id, :business_line_id, :platform_user_id, :username, :profile_url, :is_author, :contact_status, :notes, :metadata)
        """)
        db.execute(query, {
            "platform_id": data.platform_id,
            "business_line_id": data.business_line_id,
            "platform_user_id": data.platform_user_id,
            "username": data.username,
            "profile_url": data.profile_url,
            "is_author": data.is_author,
            "contact_status": data.contact_status,
            "notes": data.notes,
            "metadata": data.metadata
        })
        db.commit()

        contact_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]

        # 查询完整数据返回
        query = text("""
            SELECT c.*, p.name as platform_name, bl.name as business_line_name
            FROM contacts c
            LEFT JOIN platforms p ON c.platform_id = p.id
            LEFT JOIN business_lines bl ON c.business_line_id = bl.id
            WHERE c.id = :id
        """)
        row = db.execute(query, {"id": contact_id}).fetchone()
        return ApiResponse(result=_build_contact(row).model_dump())
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="Contact already exists for this platform")
        raise


@router.put("/{contact_id}", response_model=ApiResponse[dict])
def update_contact(contact_id: int, data: ContactUpdate, db: Session = Depends(get_db)):
    """更新触达用户"""
    row = db.execute(text("SELECT * FROM contacts WHERE id = :id"), {"id": contact_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    updates = []
    params = {"id": contact_id}

    field_map = {
        'username': data.username,
        'profile_url': data.profile_url,
        'is_author': data.is_author,
        'contact_status': data.contact_status,
        'contact_attempts': data.contact_attempts,
        'last_contact_at': data.last_contact_at,
        'notes': data.notes,
        'metadata': data.metadata,
    }

    for field, value in field_map.items():
        if value is not None:
            updates.append(f"{field} = :{field}")
            params[field] = value

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE contacts SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()

    query = text("""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contacts c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        WHERE c.id = :id
    """)
    row = db.execute(query, {"id": contact_id}).fetchone()
    return ApiResponse(result=_build_contact(row).model_dump())


@router.delete("/{contact_id}", response_model=ApiResponse[dict])
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    """删除触达用户"""
    row = db.execute(text("SELECT * FROM contacts WHERE id = :id"), {"id": contact_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    # 同时删除关联的触达历史
    db.execute(text("DELETE FROM contact_interactions WHERE contact_id = :id"), {"id": contact_id})
    db.execute(text("DELETE FROM contacts WHERE id = :id"), {"id": contact_id})
    db.commit()

    return ApiResponse(result={"message": "Contact deleted successfully"})


@router.get("/{contact_id}/interactions", response_model=ApiResponse[List[ContactInteractionResponse]])
def get_contact_interactions(contact_id: int, db: Session = Depends(get_db)):
    """获取某用户的触达历史记录"""
    # 验证用户存在
    row = db.execute(text("SELECT * FROM contacts WHERE id = :id"), {"id": contact_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    query = text("""
        SELECT * FROM contact_interactions
        WHERE contact_id = :contact_id
        ORDER BY created_at DESC
    """)
    rows = db.execute(query, {"contact_id": contact_id}).fetchall()

    interactions = [
        ContactInteractionResponse(
            id=r.id,
            contact_id=r.contact_id,
            interaction_type=r.interaction_type,
            task_execution_id=r.task_execution_id,
            detail=r.detail,
            created_at=str(r.created_at)
        )
        for r in rows
    ]

    return ApiResponse(result=interactions)


@router.post("/{contact_id}/interactions", response_model=ApiResponse[ContactInteractionResponse])
def create_contact_interaction(
    contact_id: int,
    data: ContactInteractionCreate,
    db: Session = Depends(get_db)
):
    """新增一条触达历史记录"""
    # 验证用户存在
    row = db.execute(text("SELECT * FROM contacts WHERE id = :id"), {"id": contact_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    query = text("""
        INSERT INTO contact_interactions (contact_id, interaction_type, task_execution_id, detail)
        VALUES (:contact_id, :interaction_type, :task_execution_id, :detail)
    """)
    db.execute(query, {
        "contact_id": contact_id,
        "interaction_type": data.interaction_type,
        "task_execution_id": data.task_execution_id,
        "detail": data.detail,
    })
    db.commit()

    interaction_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]

    r = db.execute(text("SELECT * FROM contact_interactions WHERE id = :id"), {"id": interaction_id}).fetchone()
    return ApiResponse(result=ContactInteractionResponse(
        id=r.id,
        contact_id=r.contact_id,
        interaction_type=r.interaction_type,
        task_execution_id=r.task_execution_id,
        detail=r.detail,
        created_at=str(r.created_at)
    ))


@router.post("/{contact_id}/mark-contacted", response_model=ApiResponse[dict])
def mark_contacted(contact_id: int, notes: Optional[str] = None, db: Session = Depends(get_db)):
    """标记为已触达"""
    row = db.execute(text("SELECT * FROM contacts WHERE id = :id"), {"id": contact_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    new_attempts = row.contact_attempts + 1

    if notes:
        db.execute(text("""
            UPDATE contacts SET contact_status = 'contacted', contact_attempts = :attempts,
            last_contact_at = CURRENT_TIMESTAMP, notes = :notes, updated_at = CURRENT_TIMESTAMP WHERE id = :id
        """), {"id": contact_id, "attempts": new_attempts, "notes": notes})
    else:
        db.execute(text("""
            UPDATE contacts SET contact_status = 'contacted', contact_attempts = :attempts,
            last_contact_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = :id
        """), {"id": contact_id, "attempts": new_attempts})
    db.commit()

    query = text("""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contacts c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        WHERE c.id = :id
    """)
    row = db.execute(query, {"id": contact_id}).fetchone()
    return ApiResponse(result=_build_contact(row).model_dump())
