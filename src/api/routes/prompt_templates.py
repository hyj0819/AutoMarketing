"""
提示词模板管理路由
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from src.core.database import get_db
from src.api.schemas.common import ApiResponse
from src.api.schemas.prompt_template import PromptTemplateCreate, PromptTemplateUpdate, PromptTemplateResponse

router = APIRouter()

# 通用 JOIN 查询片段
_JOIN_BL = """
    FROM prompt_templates pt
    LEFT JOIN business_lines bl ON pt.business_line_id = bl.id
"""
_SELECT_FIELDS = "pt.*, bl.name as business_line_name"


def _build_template_response(row) -> PromptTemplateResponse:
    """从数据库行构建响应对象"""
    return PromptTemplateResponse(
        id=row.id,
        business_line_id=row.business_line_id,
        business_line_name=row.business_line_name,
        template_code=row.template_code,
        name=row.name,
        template_content=row.template_content,
        variables=row.variables,
        version=row.version,
        status=row.status,
        is_active=row.is_active,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at),
    )


@router.get("/", response_model=ApiResponse[List[PromptTemplateResponse]])
def list_prompt_templates(
    business_line_id: Optional[int] = None,
    status: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取提示词模板列表"""
    conditions = []
    params = {}

    if business_line_id:
        conditions.append("pt.business_line_id = :business_line_id")
        params["business_line_id"] = business_line_id
    if status is not None:
        conditions.append("pt.status = :status")
        params["status"] = status

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = text(f"SELECT {_SELECT_FIELDS} {_JOIN_BL} {where_clause} ORDER BY pt.created_at DESC")
    cursor = db.execute(query, params)
    rows = cursor.fetchall()

    return ApiResponse(result=[_build_template_response(row) for row in rows])


@router.get("/{template_id}", response_model=ApiResponse[PromptTemplateResponse])
def get_prompt_template(template_id: int, db: Session = Depends(get_db)):
    """获取单个提示词模板"""
    query = text(f"SELECT {_SELECT_FIELDS} {_JOIN_BL} WHERE pt.id = :id")
    cursor = db.execute(query, {"id": template_id})
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    return ApiResponse(result=_build_template_response(row))


@router.post("/", response_model=ApiResponse[PromptTemplateResponse])
def create_prompt_template(data: PromptTemplateCreate, db: Session = Depends(get_db)):
    """创建提示词模板"""
    query = text("SELECT * FROM business_lines WHERE id = :id")
    cursor = db.execute(query, {"id": data.business_line_id})
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="业务线不存在")

    try:
        query = text("""INSERT INTO prompt_templates (business_line_id, template_code, name, template_content, variables, version, status, is_active)
           VALUES (:business_line_id, :template_code, :name, :template_content, :variables, :version, :status, :is_active)""")

        cursor = db.execute(query, {
            "business_line_id": data.business_line_id,
            "template_code": data.template_code,
            "name": data.name,
            "template_content": data.template_content,
            "variables": data.variables,
            "version": data.version,
            "status": data.status,
            "is_active": data.is_active
        })
        db.commit()

        template_id = cursor.lastrowid

        query = text(f"SELECT {_SELECT_FIELDS} {_JOIN_BL} WHERE pt.id = :id")
        cursor = db.execute(query, {"id": template_id})
        row = cursor.fetchone()

        return ApiResponse(result=_build_template_response(row))
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="该业务线下已存在相同编码的模板")
        raise


@router.put("/{template_id}", response_model=ApiResponse[PromptTemplateResponse])
def update_prompt_template(template_id: int, data: PromptTemplateUpdate, db: Session = Depends(get_db)):
    """更新提示词模板"""
    query = text("SELECT * FROM prompt_templates WHERE id = :id")
    cursor = db.execute(query, {"id": template_id})
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    updates = []
    params = {"id": template_id}

    if data.name is not None:
        updates.append("name = :name")
        params["name"] = data.name
    if data.template_content is not None:
        updates.append("template_content = :template_content")
        params["template_content"] = data.template_content
    if data.variables is not None:
        updates.append("variables = :variables")
        params["variables"] = data.variables
    if data.version is not None:
        updates.append("version = :version")
        params["version"] = data.version
    if data.status is not None:
        updates.append("status = :status")
        params["status"] = data.status
    if data.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = data.is_active

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = text(f"UPDATE prompt_templates SET {', '.join(updates)} WHERE id = :id")
        db.execute(sql, params)
        db.commit()

    query = text(f"SELECT {_SELECT_FIELDS} {_JOIN_BL} WHERE pt.id = :id")
    cursor = db.execute(query, {"id": template_id})
    row = cursor.fetchone()

    return ApiResponse(result=_build_template_response(row))


@router.post("/{template_id}/activate", response_model=ApiResponse[PromptTemplateResponse])
def activate_prompt_template(template_id: int, db: Session = Depends(get_db)):
    """激活提示词模板"""
    query = text("SELECT * FROM prompt_templates WHERE id = :id")
    cursor = db.execute(query, {"id": template_id})
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    business_line_id = row.business_line_id

    # 同一业务线下的其他模板取消激活
    db.execute(text("UPDATE prompt_templates SET is_active = 0 WHERE business_line_id = :business_line_id"), {"business_line_id": business_line_id})

    # 激活当前模板
    db.execute(text("UPDATE prompt_templates SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": template_id})
    db.commit()

    query = text(f"SELECT {_SELECT_FIELDS} {_JOIN_BL} WHERE pt.id = :id")
    cursor = db.execute(query, {"id": template_id})
    row = cursor.fetchone()

    return ApiResponse(result=_build_template_response(row))


@router.delete("/{template_id}", response_model=ApiResponse[dict])
def delete_prompt_template(template_id: int, db: Session = Depends(get_db)):
    """删除提示词模板"""
    query = text("SELECT * FROM prompt_templates WHERE id = :id")
    cursor = db.execute(query, {"id": template_id})
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    db.execute(text("DELETE FROM prompt_templates WHERE id = :id"), {"id": template_id})
    db.commit()

    return ApiResponse(result={"message": "提示词模板删除成功"})
