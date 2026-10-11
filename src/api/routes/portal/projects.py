"""项目管理：列表、新建、项目详情三 Tab（关键词 / 话术 / 账号）"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user, require_role
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.project import (
    AccountItem,
    AddKeywordsRequest,
    KeywordItem,
    PlatformOption,
    ProjectCreate,
    ProjectDetail,
    ProjectItem,
    ProjectUpdate,
    ScriptItem,
)
from src.core.database import get_db
from ._common import REACHED_IN_SQL

router = APIRouter()


@router.get("/projects/platforms", response_model=ApiResponse[list])
def list_platforms(db: Session = Depends(get_db), ctx: TenantContext = Depends(get_portal_user)):
    """可选平台。只给名称与代号，不给平台配置"""
    rows = db.execute(
        text("SELECT id, name, code FROM platforms WHERE status = 1 ORDER BY id ASC")
    ).fetchall()
    return ApiResponse(result=[PlatformOption(id=r.id, name=r.name, code=r.code) for r in rows])


@router.get("/projects", response_model=ApiResponse[list])
def list_projects(
    platform_id: int = None,
    status: int = None,
    q: str = None,
    ctx: TenantContext = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """项目列表：项目 = 平台 + 关键词 + 话术 + 账号"""
    conditions = ["bl.tenant_id = :tid", "bl.code != '__presets__'"]
    params: dict = {"tid": ctx.tenant_id}

    if platform_id:
        conditions.append("bl.platform_id = :pid")
        params["pid"] = platform_id
    if status is not None:
        conditions.append("bl.status = :st")
        params["st"] = status
    if q:
        conditions.append("bl.name LIKE :q")
        params["q"] = f"%{q}%"
    if ctx.visible_scope:
        ids = ",".join(str(i) for i in ctx.visible_scope)
        conditions.append(f"bl.id IN ({ids})")

    rows = db.execute(
        text(f"""
            SELECT bl.*, p.name AS platform_name,
                   (SELECT COUNT(*) FROM keywords k WHERE k.business_line_id = bl.id) AS keyword_count,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = bl.id) AS leads_count,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = bl.id
                        AND c.contact_status IN ({REACHED_IN_SQL})) AS reached_count,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = bl.id
                        AND c.contact_status IN ('replied', 'engaged', 'qualified', 'won', 'lost')) AS replied_count,
                   (SELECT t.name FROM prompt_templates t
                        WHERE t.business_line_id = bl.id AND t.is_active = 1 ORDER BY t.id DESC LIMIT 1) AS active_template,
                   (SELECT a.account_name FROM accounts a
                        WHERE a.id = (
                            SELECT te.account_id FROM task_executions te
                            WHERE te.business_line_id = bl.id AND te.account_id IS NOT NULL
                            ORDER BY te.id DESC LIMIT 1
                        ) LIMIT 1) AS account_name
            FROM business_lines bl
            LEFT JOIN platforms p ON bl.platform_id = p.id
            WHERE {' AND '.join(conditions)}
            ORDER BY bl.status DESC, bl.id DESC
        """),
        params,
    ).fetchall()

    items = []
    for r in rows:
        reached = int(r.reached_count or 0)
        replied = int(r.replied_count or 0)
        items.append(ProjectItem(
            id=r.id,
            name=r.name,
            platform_id=r.platform_id,
            platform_name=getattr(r, "platform_name", None),
            status=r.status,
            keyword_count=int(r.keyword_count or 0),
            active_template=r.active_template,
            account_name=r.account_name,
            leads_count=int(r.leads_count or 0),
            reached_count=reached,
            replied_count=replied,
            reply_rate=round(replied / reached * 100, 1) if reached else 0.0,
            updated_at=str(r.updated_at) if r.updated_at else None,
        ))
    return ApiResponse(result=items)


@router.post("/projects", response_model=ApiResponse[ProjectItem])
def create_project(
    data: ProjectCreate,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """新建项目：自动从平台预置话术库复制一套模板并激活"""
    name = (data.name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名不能为空")
    if not db.execute(text("SELECT id FROM platforms WHERE id = :id AND status = 1"), {"id": data.platform_id}).fetchone():
        raise HTTPException(status_code=400, detail="所选平台不存在")

    code = f"bl-{int(datetime.now().timestamp())}-{ctx.tenant_id}"
    cursor = db.execute(
        text("""
            INSERT INTO business_lines (tenant_id, platform_id, code, name, status, config)
            VALUES (:tid, :pid, :code, :name, 1, '{}')
        """),
        {"tid": ctx.tenant_id, "pid": data.platform_id, "code": code, "name": name},
    )
    bl_id = cursor.lastrowid

    preset = None
    if data.preset_template_id:
        preset = db.execute(
            text("SELECT * FROM prompt_templates WHERE id = :id AND is_preset = 1"),
            {"id": data.preset_template_id},
        ).fetchone()
    if preset is None:
        preset = db.execute(
            text("SELECT * FROM prompt_templates WHERE is_preset = 1 ORDER BY id ASC LIMIT 1")
        ).fetchone()

    if preset is not None:
        db.execute(
            text("""
                INSERT INTO prompt_templates
                    (tenant_id, business_line_id, template_code, name, template_content,
                     variables, version, status, is_active, is_preset)
                VALUES (:tid, :bl, :code, :name, :content, '[]', 1, 1, 1, 1)
            """),
            {
                "tid": ctx.tenant_id,
                "bl": bl_id,
                "code": f"{preset.template_code}-c{bl_id}",
                "name": preset.name,
                "content": preset.template_content,
            },
        )
    db.commit()

    return ApiResponse(result=_project_item(db, ctx.tenant_id, bl_id))


@router.get("/projects/{project_id}", response_model=ApiResponse[ProjectDetail])
def get_project(
    project_id: int,
    ctx: TenantContext = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """项目详情：关键词 / 话术 / 账号 三个 Tab 的数据"""
    _assert_project(db, ctx, project_id)
    project = _project_item(db, ctx.tenant_id, project_id)

    # 关键词：命中、回复、成交都按来源关键词归集
    kw_rows = db.execute(
        text("""
            SELECT k.id, k.keyword, k.priority, k.status,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = k.business_line_id
                        AND c.source_keyword = k.keyword) AS hits,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = k.business_line_id
                        AND c.source_keyword = k.keyword
                        AND c.contact_status IN ('replied', 'engaged', 'qualified', 'won', 'lost')) AS replies,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = k.business_line_id
                        AND c.source_keyword = k.keyword AND c.contact_status = 'won') AS won,
                   (SELECT COALESCE(SUM(c.deal_amount), 0) FROM contacts c
                        WHERE c.business_line_id = k.business_line_id
                          AND c.source_keyword = k.keyword AND c.contact_status = 'won') AS amount
            FROM keywords k
            WHERE k.tenant_id = :tid AND k.business_line_id = :bl
            ORDER BY k.priority DESC, k.id ASC
        """),
        {"tid": ctx.tenant_id, "bl": project_id},
    ).fetchall()
    keywords = [
        KeywordItem(
            id=r.id, keyword=r.keyword, priority=r.priority, status=r.status,
            hits=int(r.hits or 0), replies=int(r.replies or 0),
            won=int(r.won or 0), won_amount=float(r.amount or 0),
        )
        for r in kw_rows
    ]

    # 话术：本项目模板 + 平台预置库（预置库可一键复制激活）
    tpl_rows = db.execute(
        text("""
            SELECT t.*,
                   (SELECT COUNT(*) FROM contacts c WHERE c.prompt_template_id = t.id
                        AND c.contact_status IN ({reached})) AS reach,
                   (SELECT COUNT(*) FROM contacts c WHERE c.prompt_template_id = t.id
                        AND c.contact_status IN ('replied', 'engaged', 'qualified', 'won', 'lost')) AS replies
            FROM prompt_templates t
            WHERE (t.business_line_id = :bl AND t.tenant_id = :tid)
               OR (t.is_preset = 1 AND t.tenant_id = 1)
            ORDER BY t.is_preset ASC, t.is_active DESC, t.id DESC
        """.format(reached=REACHED_IN_SQL)),
        {"bl": project_id, "tid": ctx.tenant_id},
    ).fetchall()
    scripts = []
    for r in tpl_rows:
        reach, replies = int(r.reach or 0), int(r.replies or 0)
        scripts.append(ScriptItem(
            id=r.id,
            name=r.name,
            version=r.version or 1,
            status=r.status,
            is_active=1 if (r.is_active and r.business_line_id == project_id) else 0,
            is_preset=r.is_preset or 0,
            source='preset' if r.is_preset else 'project',
            preview=(r.template_content or '')[:120],
            reach=reach,
            replies=replies,
            reply_rate=round(replies / reach * 100, 1) if reach else 0.0,
        ))

    # 账号：只给名称与状态，不给 browser_id / 任何运维参数
    acc_rows = db.execute(
        text("""
            SELECT a.id, a.account_name, a.status, p.name AS platform_name,
                   (SELECT COUNT(*) FROM contacts c WHERE c.tenant_id = a.tenant_id
                        AND date(c.last_contact_at) = date('now')
                        AND c.contact_status IN ({reached})) AS sent_today
            FROM accounts a
            LEFT JOIN platforms p ON a.platform_id = p.id
            WHERE a.tenant_id = :tid
            ORDER BY a.id ASC
        """.format(reached=REACHED_IN_SQL)),
        {"tid": ctx.tenant_id},
    ).fetchall()
    accounts = [
        AccountItem(
            id=r.id,
            account_name=r.account_name,
            platform_name=r.platform_name,
            status=r.status,
            status_label='正常' if r.status == 1 else '已停用',
            sent_today=int(r.sent_today or 0),
        )
        for r in acc_rows
    ]

    return ApiResponse(result=ProjectDetail(
        project=project,
        keywords=keywords,
        scripts=scripts,
        accounts=accounts,
        managed_pool_note='托管套餐由平台账号池执行，登录态与发送节奏由平台维护，不开放调整。',
    ))


@router.patch("/projects/{project_id}", response_model=ApiResponse[ProjectItem])
def update_project(
    project_id: int,
    data: ProjectUpdate,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """改名 / 启用 / 暂停"""
    _assert_project(db, ctx, project_id)
    sets, params = [], {"id": project_id, "tid": ctx.tenant_id}
    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(status_code=400, detail="项目名不能为空")
        sets.append("name = :name")
        params["name"] = data.name.strip()
    if data.status is not None:
        sets.append("status = :st")
        params["st"] = 1 if int(data.status) else 0
    if not sets:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    sets.append("updated_at = CURRENT_TIMESTAMP")

    db.execute(
        text(f"UPDATE business_lines SET {', '.join(sets)} WHERE id = :id AND tenant_id = :tid"),
        params,
    )
    db.commit()
    return ApiResponse(result=_project_item(db, ctx.tenant_id, project_id))


@router.post("/projects/{project_id}/keywords", response_model=ApiResponse[dict])
def add_keywords(
    project_id: int,
    data: AddKeywordsRequest,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """批量添加关键词，一行一个，重复自动跳过"""
    _assert_project(db, ctx, project_id)
    created, skipped = [], []
    for raw in data.keywords:
        kw = (raw or '').strip()
        if not kw:
            continue
        exists = db.execute(
            text("SELECT id FROM keywords WHERE business_line_id = :bl AND keyword = :kw"),
            {"bl": project_id, "kw": kw},
        ).fetchone()
        if exists:
            skipped.append(kw)
            continue
        db.execute(
            text("""
                INSERT INTO keywords (tenant_id, business_line_id, keyword, priority, status)
                VALUES (:tid, :bl, :kw, :pri, 1)
            """),
            {"tid": ctx.tenant_id, "bl": project_id, "kw": kw, "pri": data.priority},
        )
        created.append(kw)
    db.commit()
    return ApiResponse(result={"created": created, "skipped": skipped, "created_count": len(created)})


@router.post("/projects/{project_id}/keywords/{keyword_id}/toggle", response_model=ApiResponse[dict])
def toggle_keyword(
    project_id: int,
    keyword_id: int,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """启用 / 禁用关键词"""
    _assert_project(db, ctx, project_id)
    row = db.execute(
        text("SELECT id, status FROM keywords WHERE id = :id AND tenant_id = :tid AND business_line_id = :bl"),
        {"id": keyword_id, "tid": ctx.tenant_id, "bl": project_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="关键词不存在")
    new_status = 0 if row.status else 1
    db.execute(text("UPDATE keywords SET status = :st WHERE id = :id"), {"st": new_status, "id": keyword_id})
    db.commit()
    return ApiResponse(result={"id": keyword_id, "status": new_status})


@router.post("/projects/{project_id}/scripts/{template_id}/activate", response_model=ApiResponse[dict])
def activate_script(
    project_id: int,
    template_id: int,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """切换激活话术。选中的是预置模板时，先复制到本项目再激活

    切换只对之后发出的私信生效，已发出的不会变。
    """
    _assert_project(db, ctx, project_id)
    tpl = db.execute(
        text("""
            SELECT * FROM prompt_templates
            WHERE id = :id AND ((business_line_id = :bl AND tenant_id = :tid) OR (is_preset = 1 AND tenant_id = 1))
        """),
        {"id": template_id, "bl": project_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not tpl:
        raise HTTPException(status_code=404, detail="话术模板不存在")

    target_id = tpl.id
    if tpl.business_line_id != project_id:
        # 预置模板：复制一份到本项目，避免跨项目共用同一条记录
        exists = db.execute(
            text("SELECT id FROM prompt_templates WHERE business_line_id = :bl AND name = :n"),
            {"bl": project_id, "n": tpl.name},
        ).fetchone()
        if exists:
            target_id = exists[0]
        else:
            cursor = db.execute(
                text("""
                    INSERT INTO prompt_templates
                        (tenant_id, business_line_id, template_code, name, template_content,
                         variables, version, status, is_active, is_preset)
                    VALUES (:tid, :bl, :code, :name, :content, '[]', 1, 1, 0, 1)
                """),
                {
                    "tid": ctx.tenant_id,
                    "bl": project_id,
                    "code": f"{tpl.template_code}-c{project_id}",
                    "name": tpl.name,
                    "content": tpl.template_content,
                },
            )
            target_id = cursor.lastrowid

    db.execute(
        text("UPDATE prompt_templates SET is_active = 0 WHERE business_line_id = :bl AND tenant_id = :tid"),
        {"bl": project_id, "tid": ctx.tenant_id},
    )
    db.execute(text("UPDATE prompt_templates SET is_active = 1, status = 1 WHERE id = :id"), {"id": target_id})
    db.commit()
    return ApiResponse(result={"active_template_id": target_id})


# ---------------- 内部函数 ----------------

def _assert_project(db: Session, ctx: TenantContext, project_id: int):
    row = db.execute(
        text("SELECT id FROM business_lines WHERE id = :id AND tenant_id = :tid"),
        {"id": project_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在")
    if ctx.visible_scope and project_id not in ctx.visible_scope:
        raise HTTPException(status_code=403, detail="该项目不在你的可见范围内")
    return row


def _project_item(db: Session, tenant_id: int, project_id: int) -> ProjectItem:
    r = db.execute(
        text("""
            SELECT bl.*, p.name AS platform_name,
                   (SELECT COUNT(*) FROM keywords k WHERE k.business_line_id = bl.id) AS keyword_count,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = bl.id) AS leads_count,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = bl.id
                        AND c.contact_status IN ({reached})) AS reached_count,
                   (SELECT COUNT(*) FROM contacts c WHERE c.business_line_id = bl.id
                        AND c.contact_status IN ('replied', 'engaged', 'qualified', 'won', 'lost')) AS replied_count,
                   (SELECT t.name FROM prompt_templates t
                        WHERE t.business_line_id = bl.id AND t.is_active = 1 ORDER BY t.id DESC LIMIT 1) AS active_template
            FROM business_lines bl
            LEFT JOIN platforms p ON bl.platform_id = p.id
            WHERE bl.id = :id AND bl.tenant_id = :tid
        """.format(reached=REACHED_IN_SQL)),
        {"id": project_id, "tid": tenant_id},
    ).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="项目不存在")

    reached = int(r.reached_count or 0)
    replied = int(r.replied_count or 0)
    return ProjectItem(
        id=r.id,
        name=r.name,
        platform_id=r.platform_id,
        platform_name=getattr(r, "platform_name", None),
        status=r.status,
        keyword_count=int(r.keyword_count or 0),
        active_template=r.active_template,
        leads_count=int(r.leads_count or 0),
        reached_count=reached,
        replied_count=replied,
        reply_rate=round(replied / reached * 100, 1) if reached else 0.0,
        updated_at=str(r.updated_at) if r.updated_at else None,
    )
