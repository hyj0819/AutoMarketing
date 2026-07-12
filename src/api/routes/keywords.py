"""
关键词管理路由
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.keyword import KeywordCreate, KeywordBatchCreate, KeywordUpdate, KeywordResponse

router = APIRouter()


@router.get("/", response_model=ApiResponse[List[KeywordResponse]])
def list_keywords(
    business_line_id: Optional[int] = None,
    status: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取关键词列表"""
    base_query = """
        SELECT k.*, bl.name as business_line_name
        FROM keywords k
        LEFT JOIN business_lines bl ON k.business_line_id = bl.id
    """
    conditions = []
    params = {}

    if business_line_id:
        conditions.append("k.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if status is not None:
        conditions.append("k.status = :status")
        params["status"] = status

    query = base_query
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY k.priority DESC, k.created_at DESC"

    cursor = db.execute(text(query), params)
    rows = cursor.fetchall()

    keywords = []
    for row in rows:
        keywords.append(KeywordResponse(
            id=row.id,
            business_line_id=row.business_line_id,
            business_line_name=row.business_line_name,
            keyword=row.keyword,
            priority=row.priority,
            status=row.status,
            created_at=str(row.created_at)
        ))

    return ApiResponse(result=keywords)


@router.post("/batch", response_model=ApiResponse[dict])
def batch_create_keywords(data: KeywordBatchCreate, db: Session = Depends(get_db)):
    """批量创建关键词"""
    # 校验业务线是否存在
    cursor = db.execute(text("SELECT * FROM business_lines WHERE id = :id"), {"id": data.business_line_id})
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="业务线不存在")

    created = []
    skipped = []

    for kw in data.keywords:
        kw = kw.strip()
        if not kw:
            continue
        try:
            cursor = db.execute(
                text("INSERT INTO keywords (business_line_id, keyword, priority, status) VALUES (:business_line_id, :keyword, :priority, :status)"),
                {
                    "business_line_id": data.business_line_id,
                    "keyword": kw,
                    "priority": data.priority,
                    "status": data.status,
                }
            )
            db.commit()
            created.append(kw)
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                db.rollback()
                skipped.append(kw)
            else:
                db.rollback()
                raise

    return ApiResponse(result={
        "created_count": len(created),
        "created": created,
        "skipped": skipped,
    })


@router.post("/", response_model=ApiResponse[KeywordResponse])
def create_keyword(data: KeywordCreate, db: Session = Depends(get_db)):
    """创建关键词"""
    try:
        query = text("""INSERT INTO keywords (business_line_id, keyword, priority, status)
           VALUES (:business_line_id, :keyword, :priority, :status)""")

        cursor = db.execute(query, {
            "business_line_id": data.business_line_id,
            "keyword": data.keyword,
            "priority": data.priority,
            "status": data.status
        })
        db.commit()

        keyword_id = cursor.lastrowid

        query = text("""
            SELECT k.*, bl.name as business_line_name
            FROM keywords k
            LEFT JOIN business_lines bl ON k.business_line_id = bl.id
            WHERE k.id = :id
        """)
        cursor = db.execute(query, {"id": keyword_id})
        row = cursor.fetchone()

        return ApiResponse(result=KeywordResponse(
            id=row.id,
            business_line_id=row.business_line_id,
            business_line_name=row.business_line_name,
            keyword=row.keyword,
            priority=row.priority,
            status=row.status,
            created_at=str(row.created_at)
        ))
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="关键词已存在")
        raise


@router.put("/{keyword_id}", response_model=ApiResponse[KeywordResponse])
def update_keyword(keyword_id: int, data: KeywordUpdate, db: Session = Depends(get_db)):
    """更新关键词"""
    query = text("SELECT * FROM keywords WHERE id = :id")
    cursor = db.execute(query, {"id": keyword_id})
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="关键词不存在")

    updates = []
    params = {"id": keyword_id}

    if data.keyword is not None:
        updates.append("keyword = :keyword")
        params["keyword"] = data.keyword
    if data.priority is not None:
        updates.append("priority = :priority")
        params["priority"] = data.priority
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status

    if updates:
        sql = text(f"UPDATE keywords SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()

    query = text("""
        SELECT k.*, bl.name as business_line_name
        FROM keywords k
        LEFT JOIN business_lines bl ON k.business_line_id = bl.id
        WHERE k.id = :id
    """)
    cursor = db.execute(query, {"id": keyword_id})
    row = cursor.fetchone()

    return ApiResponse(result=KeywordResponse(
        id=row.id,
        business_line_id=row.business_line_id,
        business_line_name=row.business_line_name,
        keyword=row.keyword,
        priority=row.priority,
        status=row.status,
        created_at=str(row.created_at)
    ))


@router.delete("/{keyword_id}", response_model=ApiResponse[dict])
def delete_keyword(keyword_id: int, db: Session = Depends(get_db)):
    """删除关键词"""
    query = text("SELECT * FROM keywords WHERE id = :id")
    cursor = db.execute(query, {"id": keyword_id})
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="关键词不存在")

    db.execute(text("DELETE FROM keywords WHERE id = :id"), {"id": keyword_id})
    db.commit()

    return ApiResponse(result={"message": "关键词删除成功"})

