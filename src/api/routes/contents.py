"""
内容数据管理路由
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
import io
import csv

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.content import ContentCreate, ContentUpdate, ContentResponse

router = APIRouter()


def _build_content_response(row) -> ContentResponse:
    """从数据库行构建 ContentResponse"""
    return ContentResponse(
        id=row.id,
        platform_id=row.platform_id,
        platform_name=getattr(row, 'platform_name', None),
        business_line_id=row.business_line_id,
        business_line_name=getattr(row, 'business_line_name', None),
        content_type=row.content_type,
        content_id=row.content_id,
        content_url=row.content_url,
        title=row.title,
        content_text=row.content_text,
        author_id=row.author_id,
        author_name=row.author_name,
        engagement_stats=row.engagement_stats,
        ai_analysis_result=row.ai_analysis_result,
        source_keyword=row.source_keyword,
        scraped_at=str(row.scraped_at)
    )


@router.get("/", response_model=ApiResponse[dict])
def list_contents(
    page: int = 1,
    pageSize: int = 10,
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    content_type: Optional[str] = None,
    source_keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取内容数据列表（分页+筛选）"""
    conditions = []
    params = {}

    if platform_id:
        conditions.append("c.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if business_line_id:
        conditions.append("c.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if content_type:
        conditions.append("c.content_type = :content_type")
        params["content_type"] = content_type
    if source_keyword:
        conditions.append("c.source_keyword LIKE :source_keyword")
        params["source_keyword"] = f"%{source_keyword}%"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    # 查询总数
    count_sql = text(f"""
        SELECT COUNT(*) as total
        FROM contents c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        {where_clause}
    """)
    total = db.execute(count_sql, params).fetchone()[0]

    # 分页查询
    offset = (page - 1) * pageSize
    query_sql = text(f"""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contents c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        {where_clause}
        ORDER BY c.scraped_at DESC
        LIMIT :limit OFFSET :offset
    """)
    params["limit"] = pageSize
    params["offset"] = offset
    rows = db.execute(query_sql, params).fetchall()

    contents = [_build_content_response(row) for row in rows]

    return ApiResponse(result={
        "list": [c.model_dump() for c in contents],
        "pageCount": (total + pageSize - 1) // pageSize if total > 0 else 0,
        "itemCount": total,
    })


@router.get("/export")
def export_contents(
    platform_id: Optional[int] = None,
    business_line_id: Optional[int] = None,
    content_type: Optional[str] = None,
    source_keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """导出内容数据为CSV"""
    conditions = []
    params = {}

    if platform_id:
        conditions.append("c.platform_id = :platform_id")
        params["platform_id"] = platform_id
    if business_line_id:
        conditions.append("c.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if content_type:
        conditions.append("c.content_type = :content_type")
        params["content_type"] = content_type
    if source_keyword:
        conditions.append("c.source_keyword LIKE :source_keyword")
        params["source_keyword"] = f"%{source_keyword}%"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    query_sql = text(f"""
        SELECT c.id, p.name as platform_name, bl.name as business_line_name,
               c.content_type, c.title, c.author_name, c.source_keyword,
               c.engagement_stats, c.scraped_at
        FROM contents c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        {where_clause}
        ORDER BY c.scraped_at DESC
    """)
    rows = db.execute(query_sql, params).fetchall()

    # 生成 CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', '平台', '业务线', '内容类型', '标题', '作者',
        '来源关键词', '互动数据', '采集时间'
    ])

    type_map = {'post': '帖子', 'comment': '评论', 'video': '视频', 'image': '图片'}
    for row in rows:
        writer.writerow([
            row.id,
            row.platform_name or '',
            row.business_line_name or '',
            type_map.get(row.content_type, row.content_type),
            row.title or '',
            row.author_name or '',
            row.source_keyword or '',
            row.engagement_stats or '',
            str(row.scraped_at),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contents_export.csv"}
    )


@router.get("/{content_id}", response_model=ApiResponse[dict])
def get_content(content_id: int, db: Session = Depends(get_db)):
    """获取单个内容数据"""
    query = text("""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contents c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        WHERE c.id = :id
    """)
    row = db.execute(query, {"id": content_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    return ApiResponse(result=_build_content_response(row).model_dump())


@router.post("/", response_model=ApiResponse[dict])
def create_content(data: ContentCreate, db: Session = Depends(get_db)):
    """创建内容数据"""
    # 验证平台
    if not db.execute(text("SELECT * FROM platforms WHERE id = :id"), {"id": data.platform_id}).fetchone():
        raise HTTPException(status_code=404, detail="Platform not found")

    # 验证业务线
    if not db.execute(text("SELECT * FROM business_lines WHERE id = :id"), {"id": data.business_line_id}).fetchone():
        raise HTTPException(status_code=404, detail="Business line not found")

    try:
        query = text("""
            INSERT INTO contents (platform_id, business_line_id, content_type, content_id, content_url, title, content_text, author_id, author_name, engagement_stats, ai_analysis_result, source_keyword)
            VALUES (:platform_id, :business_line_id, :content_type, :content_id, :content_url, :title, :content_text, :author_id, :author_name, :engagement_stats, :ai_analysis_result, :source_keyword)
        """)
        db.execute(query, {
            "platform_id": data.platform_id,
            "business_line_id": data.business_line_id,
            "content_type": data.content_type,
            "content_id": data.content_id,
            "content_url": data.content_url,
            "title": data.title,
            "content_text": data.content_text,
            "author_id": data.author_id,
            "author_name": data.author_name,
            "engagement_stats": data.engagement_stats,
            "ai_analysis_result": data.ai_analysis_result,
            "source_keyword": data.source_keyword
        })
        db.commit()

        content_db_id = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]

        query = text("""
            SELECT c.*, p.name as platform_name, bl.name as business_line_name
            FROM contents c
            LEFT JOIN platforms p ON c.platform_id = p.id
            LEFT JOIN business_lines bl ON c.business_line_id = bl.id
            WHERE c.id = :id
        """)
        row = db.execute(query, {"id": content_db_id}).fetchone()
        return ApiResponse(result=_build_content_response(row).model_dump())
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="Content already exists for this platform")
        raise


@router.put("/{content_id}", response_model=ApiResponse[dict])
def update_content(content_id: int, data: ContentUpdate, db: Session = Depends(get_db)):
    """更新内容数据"""
    row = db.execute(text("SELECT * FROM contents WHERE id = :id"), {"id": content_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    updates = []
    params = {"id": content_id}

    field_map = {
        'title': data.title,
        'content_text': data.content_text,
        'engagement_stats': data.engagement_stats,
        'ai_analysis_result': data.ai_analysis_result,
    }

    for field, value in field_map.items():
        if value is not None:
            updates.append(f"{field} = :{field}")
            params[field] = value

    if updates:
        sql = text(f"UPDATE contents SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()

    query = text("""
        SELECT c.*, p.name as platform_name, bl.name as business_line_name
        FROM contents c
        LEFT JOIN platforms p ON c.platform_id = p.id
        LEFT JOIN business_lines bl ON c.business_line_id = bl.id
        WHERE c.id = :id
    """)
    row = db.execute(query, {"id": content_id}).fetchone()
    return ApiResponse(result=_build_content_response(row).model_dump())


@router.delete("/{content_id}", response_model=ApiResponse[dict])
def delete_content(content_id: int, db: Session = Depends(get_db)):
    """删除内容数据"""
    row = db.execute(text("SELECT * FROM contents WHERE id = :id"), {"id": content_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    db.execute(text("DELETE FROM contents WHERE id = :id"), {"id": content_id})
    db.commit()

    return ApiResponse(result={"message": "Content deleted successfully"})
