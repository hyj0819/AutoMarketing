"""
统计分析路由
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from src.core.database import get_db
from src.api.schemas.common import ApiResponse

router = APIRouter()


def _build_date_filter(start_date: Optional[str], end_date: Optional[str]) -> tuple:
    """构建日期过滤条件，返回 (sql_clause, params_dict)"""
    conditions = []
    params = {}
    if start_date:
        conditions.append("AND created_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("AND created_at <= :end_date")
        params["end_date"] = end_date + " 23:59:59"
    return " ".join(conditions), params


def _build_date_filter_contents(start_date: Optional[str], end_date: Optional[str]) -> tuple:
    """为 contents 表构建日期过滤（使用 scraped_at）"""
    conditions = []
    params = {}
    if start_date:
        conditions.append("AND scraped_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("AND scraped_at <= :end_date")
        params["end_date"] = end_date + " 23:59:59"
    return " ".join(conditions), params


# ──────────────────────────────────────────────
# 1. 统计概览（核心指标卡片）
# ──────────────────────────────────────────────
@router.get("/overview", response_model=ApiResponse[Dict[str, Any]])
def get_stats_overview(
    business_line_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    获取统计概览：总采集内容、总触达用户、已联系、已转化、转化率。
    支持按 business_line_id 和日期范围过滤。
    """
    bl_filter = "AND business_line_id = :bl_id" if business_line_id else ""
    bl_params = {"bl_id": business_line_id} if business_line_id else {}

    date_filter_contents, date_params_contents = _build_date_filter_contents(start_date, end_date)
    date_filter_contacts, date_params_contacts = _build_date_filter(start_date, end_date)

    # 总采集内容
    sql = f"SELECT COUNT(*) FROM contents WHERE 1=1 {bl_filter} {date_filter_contents}"
    contents_total = db.execute(text(sql), {**bl_params, **date_params_contents}).fetchone()[0]

    # 总触达用户
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter} {date_filter_contacts}"
    contacts_total = db.execute(text(sql), {**bl_params, **date_params_contacts}).fetchone()[0]

    # 已联系（contact_status = 'contacted'）
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter} {date_filter_contacts} AND contact_status = 'contacted'"
    contacted = db.execute(text(sql), {**bl_params, **date_params_contacts}).fetchone()[0]

    # 已转化（contact_status = 'converted'）
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter} {date_filter_contacts} AND contact_status = 'converted'"
    converted = db.execute(text(sql), {**bl_params, **date_params_contacts}).fetchone()[0]

    # AI筛选通过（contact_status != 'pending'，即已被处理过的）
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter} {date_filter_contacts} AND contact_status != 'pending'"
    ai_passed = db.execute(text(sql), {**bl_params, **date_params_contacts}).fetchone()[0]

    # 已发送私信（contact_attempts > 0）
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter} {date_filter_contacts} AND contact_attempts > 0"
    messaged = db.execute(text(sql), {**bl_params, **date_params_contacts}).fetchone()[0]

    # 转化率
    conversion_rate = round(converted / contacts_total * 100, 2) if contacts_total > 0 else 0
    contact_rate = round(contacted / contacts_total * 100, 2) if contacts_total > 0 else 0

    # 运行中任务
    sql = "SELECT COUNT(*) FROM task_executions WHERE status = 'running'"
    running_tasks = db.execute(text(sql)).fetchone()[0]

    return ApiResponse(result={
        "total_contents": contents_total,
        "total_contacts": contacts_total,
        "contacted": contacted,
        "converted": converted,
        "ai_passed": ai_passed,
        "messaged": messaged,
        "conversion_rate": conversion_rate,
        "contact_rate": contact_rate,
        "running_tasks": running_tasks,
    })


# ──────────────────────────────────────────────
# 2. 触达用户统计
# ──────────────────────────────────────────────
@router.get("/contacts", response_model=ApiResponse[Dict[str, Any]])
def get_contacts_stats(
    business_line_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """触达用户统计：按平台和业务线分组"""
    # 按平台分组
    conditions = []
    params = {}
    if business_line_id:
        conditions.append("c.business_line_id = :bl_id")
        params["bl_id"] = business_line_id
    if start_date:
        conditions.append("c.created_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("c.created_at <= :end_date")
        params["end_date"] = end_date + " 23:59:59"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"""
        SELECT p.code, p.name,
               COUNT(c.id) as total,
               SUM(CASE WHEN c.contact_status = 'contacted' THEN 1 ELSE 0 END) as contacted,
               SUM(CASE WHEN c.contact_status = 'converted' THEN 1 ELSE 0 END) as converted,
               SUM(CASE WHEN c.contact_attempts > 0 THEN 1 ELSE 0 END) as messaged
        FROM platforms p
        LEFT JOIN contacts c ON p.id = c.platform_id
        {where_clause}
        GROUP BY p.id
        ORDER BY total DESC
    """
    rows = db.execute(text(sql), params).fetchall()
    by_platform = [
        {
            "platform_code": r[0],
            "platform_name": r[1],
            "total": r[2],
            "contacted": r[3] or 0,
            "converted": r[4] or 0,
            "messaged": r[5] or 0,
        }
        for r in rows
    ]

    # 按业务线分组
    conditions_bl = []
    params_bl = {}
    if business_line_id:
        conditions_bl.append("c.business_line_id = :bl_id")
        params_bl["bl_id"] = business_line_id
    if start_date:
        conditions_bl.append("c.created_at >= :start_date")
        params_bl["start_date"] = start_date
    if end_date:
        conditions_bl.append("c.created_at <= :end_date")
        params_bl["end_date"] = end_date + " 23:59:59"

    where_bl = "WHERE " + " AND ".join(conditions_bl) if conditions_bl else ""

    sql = f"""
        SELECT bl.id, bl.code, bl.name, p.name as platform_name,
               COUNT(c.id) as total,
               SUM(CASE WHEN c.contact_status = 'contacted' THEN 1 ELSE 0 END) as contacted,
               SUM(CASE WHEN c.contact_status = 'converted' THEN 1 ELSE 0 END) as converted
        FROM business_lines bl
        LEFT JOIN platforms p ON bl.platform_id = p.id
        LEFT JOIN contacts c ON bl.id = c.business_line_id
        {where_bl}
        GROUP BY bl.id
        ORDER BY total DESC
    """
    rows = db.execute(text(sql), params_bl).fetchall()
    by_business_line = [
        {
            "business_line_id": r[0],
            "business_line_code": r[1],
            "business_line_name": r[2],
            "platform_name": r[3],
            "total": r[4],
            "contacted": r[5] or 0,
            "converted": r[6] or 0,
        }
        for r in rows
    ]

    return ApiResponse(result={
        "by_platform": by_platform,
        "by_business_line": by_business_line,
    })


# ──────────────────────────────────────────────
# 3. 内容数据统计
# ──────────────────────────────────────────────
@router.get("/contents", response_model=ApiResponse[Dict[str, Any]])
def get_contents_stats(
    business_line_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """内容数据统计：按平台和类型分组"""
    conditions = []
    params = {}
    if business_line_id:
        conditions.append("c.business_line_id = :bl_id")
        params["bl_id"] = business_line_id
    if start_date:
        conditions.append("c.scraped_at >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("c.scraped_at <= :end_date")
        params["end_date"] = end_date + " 23:59:59"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    # 按平台分组
    sql = f"""
        SELECT p.code, p.name,
               COUNT(c.id) as total,
               SUM(CASE WHEN c.ai_analysis_result IS NOT NULL AND c.ai_analysis_result != '' THEN 1 ELSE 0 END) as ai_analyzed
        FROM platforms p
        LEFT JOIN contents c ON p.id = c.platform_id
        {where_clause}
        GROUP BY p.id
        ORDER BY total DESC
    """
    rows = db.execute(text(sql), params).fetchall()
    by_platform = [
        {
            "platform_code": r[0],
            "platform_name": r[1],
            "total": r[2],
            "ai_analyzed": r[3] or 0,
        }
        for r in rows
    ]

    # 按内容类型分组
    sql = f"""
        SELECT c.content_type,
               COUNT(c.id) as total
        FROM contents c
        {where_clause}
        GROUP BY c.content_type
        ORDER BY total DESC
    """
    rows = db.execute(text(sql), params).fetchall()
    by_type = [{"content_type": r[0], "total": r[1]} for r in rows]

    return ApiResponse(result={
        "by_platform": by_platform,
        "by_type": by_type,
    })


# ──────────────────────────────────────────────
# 4. 转化漏斗
# ──────────────────────────────────────────────
@router.get("/pipeline", response_model=ApiResponse[Dict[str, Any]])
def get_pipeline_stats(
    business_line_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    转化漏斗：采集内容 -> AI筛选通过 -> 已发送私信 -> 已联系 -> 已转化
    """
    bl_filter_c = "AND business_line_id = :bl_id" if business_line_id else ""
    bl_params = {"bl_id": business_line_id} if business_line_id else {}

    # contents 用 scraped_at
    date_c = ""
    params_c = {**bl_params}
    if start_date:
        date_c += " AND scraped_at >= :start_date"
        params_c["start_date"] = start_date
    if end_date:
        date_c += " AND scraped_at <= :end_date"
        params_c["end_date"] = end_date + " 23:59:59"

    # contacts 用 created_at
    date_ct = ""
    params_ct = {**bl_params}
    if start_date:
        date_ct += " AND created_at >= :start_date"
        params_ct["start_date"] = start_date
    if end_date:
        date_ct += " AND created_at <= :end_date"
        params_ct["end_date"] = end_date + " 23:59:59"

    # 1) 采集内容总数
    sql = f"SELECT COUNT(*) FROM contents WHERE 1=1 {bl_filter_c} {date_c}"
    total_contents = db.execute(text(sql), params_c).fetchone()[0]

    # 2) AI筛选通过（ai_analysis_result 不为空）
    sql = f"SELECT COUNT(*) FROM contents WHERE 1=1 {bl_filter_c} {date_c} AND ai_analysis_result IS NOT NULL AND ai_analysis_result != ''"
    ai_filtered = db.execute(text(sql), params_c).fetchone()[0]

    # 3) 已发送私信（contact_attempts > 0）
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter_c} {date_ct} AND contact_attempts > 0"
    messaged = db.execute(text(sql), params_ct).fetchone()[0]

    # 4) 已联系
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter_c} {date_ct} AND contact_status IN ('contacted', 'converted')"
    contacted = db.execute(text(sql), params_ct).fetchone()[0]

    # 5) 已转化
    sql = f"SELECT COUNT(*) FROM contacts WHERE 1=1 {bl_filter_c} {date_ct} AND contact_status = 'converted'"
    converted = db.execute(text(sql), params_ct).fetchone()[0]

    stages = [
        {"name": "采集内容", "value": total_contents, "rate": 100.0 if total_contents > 0 else 0},
        {"name": "AI筛选通过", "value": ai_filtered, "rate": round(ai_filtered / total_contents * 100, 1) if total_contents > 0 else 0},
        {"name": "已发送私信", "value": messaged, "rate": round(messaged / ai_filtered * 100, 1) if ai_filtered > 0 else 0},
        {"name": "已联系", "value": contacted, "rate": round(contacted / messaged * 100, 1) if messaged > 0 else 0},
        {"name": "已转化", "value": converted, "rate": round(converted / contacted * 100, 1) if contacted > 0 else 0},
    ]

    return ApiResponse(result={"stages": stages})


# ──────────────────────────────────────────────
# 5. 趋势分析
# ──────────────────────────────────────────────
@router.get("/trend", response_model=ApiResponse[Dict[str, Any]])
def get_trend_data(
    business_line_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
):
    """
    趋势分析：每日/每周/每月 新增采集内容、触达用户、发送私信数。
    默认查询最近30天。
    """
    # 默认日期范围：最近30天
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    bl_filter = "AND business_line_id = :bl_id" if business_line_id else ""
    bl_params = {"bl_id": business_line_id} if business_line_id else {}

    # 根据粒度确定 SQLite 日期分组格式
    if granularity == "day":
        date_fmt = "%Y-%m-%d"
    elif granularity == "week":
        date_fmt = "%Y-W%W"
    else:
        date_fmt = "%Y-%m"

    # 采集内容趋势（按 scraped_at）
    sql = f"""
        SELECT DATE(scraped_at) as d, COUNT(*) as cnt
        FROM contents
        WHERE scraped_at >= :start_date AND scraped_at <= :end_date
        {bl_filter}
        GROUP BY DATE(scraped_at)
        ORDER BY d
    """
    params = {**bl_params, "start_date": start_date, "end_date": end_date + " 23:59:59"}
    rows = db.execute(text(sql), params).fetchall()
    contents_by_date = {str(r[0]): r[1] for r in rows}

    # 触达用户趋势（按 created_at）
    sql = f"""
        SELECT DATE(created_at) as d, COUNT(*) as cnt
        FROM contacts
        WHERE created_at >= :start_date AND created_at <= :end_date
        {bl_filter}
        GROUP BY DATE(created_at)
        ORDER BY d
    """
    rows = db.execute(text(sql), params).fetchall()
    contacts_by_date = {str(r[0]): r[1] for r in rows}

    # 发送私信趋势（按 last_contact_at）
    sql = f"""
        SELECT DATE(last_contact_at) as d, COUNT(*) as cnt
        FROM contacts
        WHERE last_contact_at IS NOT NULL
          AND last_contact_at >= :start_date AND last_contact_at <= :end_date
        {bl_filter}
        GROUP BY DATE(last_contact_at)
        ORDER BY d
    """
    rows = db.execute(text(sql), params).fetchall()
    messages_by_date = {str(r[0]): r[1] for r in rows}

    # 生成完整日期序列（填充无数据的日期为0）
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    # 按粒度聚合
    if granularity == "day":
        trend = [
            {
                "date": d,
                "contents": contents_by_date.get(d, 0),
                "contacts": contacts_by_date.get(d, 0),
                "messages": messages_by_date.get(d, 0),
            }
            for d in dates
        ]
    else:
        # 按周或月聚合
        from collections import defaultdict
        agg = defaultdict(lambda: {"contents": 0, "contacts": 0, "messages": 0})
        for d in dates:
            dt = datetime.strptime(d, "%Y-%m-%d")
            if granularity == "week":
                key = dt.strftime("%Y-W%W")
            else:
                key = dt.strftime("%Y-%m")
            agg[key]["contents"] += contents_by_date.get(d, 0)
            agg[key]["contacts"] += contacts_by_date.get(d, 0)
            agg[key]["messages"] += messages_by_date.get(d, 0)

        trend = [
            {"date": k, **v}
            for k, v in sorted(agg.items())
        ]

    return ApiResponse(result={
        "granularity": granularity,
        "start_date": start_date,
        "end_date": end_date,
        "data": trend,
    })


# ──────────────────────────────────────────────
# 以下为保留的原有接口
# ──────────────────────────────────────────────
@router.get("/contacts/by-platform", response_model=ApiResponse[Dict[str, Any]])
def get_contacts_by_platform(db: Session = Depends(get_db)):
    """获取各平台触达用户统计"""
    query = text("""
        SELECT p.code, p.name, COUNT(c.id) as total,
               SUM(CASE WHEN c.contact_status = 'contacted' THEN 1 ELSE 0 END) as contacted,
               SUM(CASE WHEN c.is_author = 1 THEN 1 ELSE 0 END) as authors
        FROM platforms p
        LEFT JOIN contacts c ON p.id = c.platform_id
        GROUP BY p.id
        ORDER BY total DESC
    """)
    rows = db.execute(query).fetchall()
    result = [
        {"platform_code": r[0], "platform_name": r[1], "total": r[2], "contacted": r[3], "authors": r[4]}
        for r in rows
    ]
    return ApiResponse(result=result)


@router.get("/contacts/by-business-line", response_model=ApiResponse[Dict[str, Any]])
def get_contacts_by_business_line(db: Session = Depends(get_db)):
    """获取各业务线触达用户统计"""
    query = text("""
        SELECT bl.code, bl.name, COUNT(c.id) as total,
               SUM(CASE WHEN c.contact_status = 'contacted' THEN 1 ELSE 0 END) as contacted
        FROM business_lines bl
        LEFT JOIN contacts c ON bl.id = c.business_line_id
        GROUP BY bl.id
        ORDER BY total DESC
    """)
    rows = db.execute(query).fetchall()
    result = [
        {"business_line_code": r[0], "business_line_name": r[1], "total": r[2], "contacted": r[3]}
        for r in rows
    ]
    return ApiResponse(result=result)


@router.get("/contents/by-platform", response_model=ApiResponse[Dict[str, Any]])
def get_contents_by_platform(db: Session = Depends(get_db)):
    """获取各平台内容数据统计"""
    query = text("""
        SELECT p.code, p.name, COUNT(c.id) as total,
               SUM(CASE WHEN c.ai_analysis_result IS NOT NULL THEN 1 ELSE 0 END) as analyzed
        FROM platforms p
        LEFT JOIN contents c ON p.id = c.platform_id
        GROUP BY p.id
        ORDER BY total DESC
    """)
    rows = db.execute(query).fetchall()
    result = [
        {"platform_code": r[0], "platform_name": r[1], "total": r[2], "analyzed": r[3]}
        for r in rows
    ]
    return ApiResponse(result=result)


@router.get("/tasks/recent", response_model=ApiResponse[Dict[str, Any]])
def get_recent_tasks(limit: int = 10, db: Session = Depends(get_db)):
    """获取最近任务执行记录"""
    query = text("""
        SELECT t.id, t.task_type, bl.name as business_line_name, t.status, 
               t.total_items, t.success_items, t.failed_items, t.created_at
        FROM task_executions t
        LEFT JOIN business_lines bl ON t.business_line_id = bl.id
        ORDER BY t.created_at DESC
        LIMIT :limit
    """)
    rows = db.execute(query, {"limit": limit}).fetchall()
    result = [
        {
            "id": r[0], "task_type": r[1], "business_line_name": r[2], "status": r[3],
            "total_items": r[4], "success_items": r[5], "failed_items": r[6], "created_at": str(r[7]),
        }
        for r in rows
    ]
    return ApiResponse(result=result)


@router.get("/keywords/top", response_model=ApiResponse[Dict[str, Any]])
def get_top_keywords(limit: int = 10, db: Session = Depends(get_db)):
    """获取高频关键词"""
    query = text("""
        SELECT k.keyword, bl.name as business_line_name, k.priority,
               COUNT(c.id) as matched_contents
        FROM keywords k
        LEFT JOIN business_lines bl ON k.business_line_id = bl.id
        LEFT JOIN contents c ON c.source_keyword LIKE '%' || k.keyword || '%'
        WHERE k.status = 1
        GROUP BY k.id
        ORDER BY matched_contents DESC, k.priority DESC
        LIMIT :limit
    """)
    rows = db.execute(query, {"limit": limit}).fetchall()
    result = [
        {"keyword": r[0], "business_line_name": r[1], "priority": r[2], "matched_contents": r[3]}
        for r in rows
    ]
    return ApiResponse(result=result)
