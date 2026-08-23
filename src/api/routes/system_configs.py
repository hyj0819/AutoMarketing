"""
系统参数配置路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse

router = APIRouter()


@router.get("/")
def list_configs(
    config_group: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取系统参数列表（可按分组筛选）"""
    conditions = []
    params: dict = {}

    if config_group:
        conditions.append("config_group = :config_group")
        params["config_group"] = config_group

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = text(f"""
        SELECT * FROM system_configs
        {where_clause}
        ORDER BY config_group, sort_order
    """)
    rows = db.execute(sql, params).fetchall()

    items = [
        {
            "id": row.id,
            "config_group": row.config_group,
            "config_key": row.config_key,
            "config_value": row.config_value,
            "value_type": row.value_type,
            "label": row.label,
            "description": row.description,
            "sort_order": row.sort_order,
            "updated_at": str(row.updated_at),
        }
        for row in rows
    ]

    return ApiResponse(result=items)


@router.get("/groups")
def list_groups(db: Session = Depends(get_db)):
    """获取所有参数分组"""
    sql = text("""
        SELECT DISTINCT config_group FROM system_configs ORDER BY config_group
    """)
    rows = db.execute(sql).fetchall()
    groups = [
        {"value": row[0], "label": _group_label(row[0])}
        for row in rows
    ]
    return ApiResponse(result=groups)


def _group_label(group: str) -> str:
    """分组中文标签"""
    labels = {
        "risk_control": "风控策略",
        "ai": "AI 配置",
        "system": "系统参数",
        "worker": "Worker 配置",
    }
    return labels.get(group, group)


@router.get("/{config_id}")
def get_config(config_id: int, db: Session = Depends(get_db)):
    """获取单个系统参数"""
    row = db.execute(
        text("SELECT * FROM system_configs WHERE id = :id"),
        {"id": config_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="参数不存在")

    return ApiResponse(result={
        "id": row.id,
        "config_group": row.config_group,
        "config_key": row.config_key,
        "config_value": row.config_value,
        "value_type": row.value_type,
        "label": row.label,
        "description": row.description,
        "sort_order": row.sort_order,
        "updated_at": str(row.updated_at),
    })


@router.put("/{config_id}")
def update_config(config_id: int, data: dict, db: Session = Depends(get_db)):
    """更新单个系统参数"""
    row = db.execute(
        text("SELECT * FROM system_configs WHERE id = :id"),
        {"id": config_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="参数不存在")

    config_value = data.get("config_value")
    if config_value is None:
        raise HTTPException(status_code=400, detail="config_value 不能为空")

    db.execute(
        text("""
            UPDATE system_configs
            SET config_value = :value, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {"value": str(config_value), "id": config_id},
    )
    db.commit()

    return ApiResponse(result={"message": "更新成功"})


@router.put("/batch")
def batch_update_configs(data: dict, db: Session = Depends(get_db)):
    """批量更新系统参数

    data 格式: { "updates": [ {"id": 1, "config_value": "10"}, ... ] }
    """
    updates = data.get("updates", [])
    if not updates:
        raise HTTPException(status_code=400, detail="更新列表不能为空")

    updated_count = 0
    for item in updates:
        config_id = item.get("id")
        config_value = item.get("config_value")
        if config_id is None or config_value is None:
            continue
        db.execute(
            text("""
                UPDATE system_configs
                SET config_value = :value, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"value": str(config_value), "id": int(config_id)},
        )
        updated_count += 1

    db.commit()
    return ApiResponse(result={"message": f"已更新 {updated_count} 个参数", "updated_count": updated_count})
