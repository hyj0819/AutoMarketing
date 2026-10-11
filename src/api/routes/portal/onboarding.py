"""新手引导：四步跑出第一个结果

步骤：建项目 → 填关键词 → 选话术 → 启动任务。

设计要点：
1. 引导态挂在租户上（`tenants.onboarding_step`），团队里任何成员推进都算数，
   避免同一个人换台电脑就从头再来，也避免两个人各走一遍
2. 每一步都是真实写操作，不是「下一步、下一步、完成」的假流程。
   走完引导，客户手里就已经有一个在跑的任务
3. 每一步都可以单独重做，引导完成后这些接口仍然可用，不会把客户锁死
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps.portal import TenantContext, get_portal_user, require_role
from src.api.schemas.common import ApiResponse
from src.api.schemas.portal.onboarding import (
    OnboardingKeywordsRequest,
    OnboardingLaunchRequest,
    OnboardingProjectRequest,
    OnboardingScriptRequest,
    OnboardingStatus,
    OnboardingStepItem,
    OnboardingStepResult,
    PresetScriptOption,
)
from src.core.database import get_db
from ._common import build_scrape_task_config

router = APIRouter()

TOTAL_STEPS = 4

STEP_DEFS = [
    ("project", "建一个项目", "选平台和项目名，系统会自动带一套话术模板"),
    ("keywords", "填关键词", "告诉系统在哪些内容下面找人，一行一个"),
    ("script", "选一套话术", "决定私信怎么开口，之后随时能换"),
    ("launch", "启动第一个任务", "跑一次采集，任务完成后就能在线索池看到结果"),
]


@router.get("/onboarding", response_model=ApiResponse[OnboardingStatus])
def get_onboarding(ctx: TenantContext = Depends(get_portal_user), db: Session = Depends(get_db)):
    """引导状态：当前走到第几步、可选平台、预置话术"""
    tenant = _tenant(db, ctx.tenant_id)
    project_id = tenant.onboarding_project_id
    project_name = None
    if project_id:
        row = db.execute(
            text("SELECT name FROM business_lines WHERE id = :id AND tenant_id = :tid"),
            {"id": project_id, "tid": ctx.tenant_id},
        ).fetchone()
        if row:
            project_name = row.name
        else:
            project_id = None  # 项目被删了，回退到第一步重来

    step = _current_step(tenant)
    return ApiResponse(result=OnboardingStatus(
        done=bool(tenant.onboarding_done),
        current_step=step,
        total_steps=TOTAL_STEPS,
        project_id=project_id,
        project_name=project_name,
        steps=_step_items(step, bool(tenant.onboarding_done)),
        platforms=_platforms(db),
        presets=_presets(db),
    ))


@router.post("/onboarding/project", response_model=ApiResponse[OnboardingStepResult])
def onboarding_create_project(
    data: OnboardingProjectRequest,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """第一步：建项目，并自动复制一套预置话术进去"""
    name = (data.name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名不能为空")
    if not db.execute(
        text("SELECT id FROM platforms WHERE id = :id AND status = 1"), {"id": data.platform_id}
    ).fetchone():
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

    # 预置话术：客户指定优先，没指定就取库里第一条，保证项目一建好就有话术可用
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

    _advance(db, ctx.tenant_id, project_id=bl_id)
    return ApiResponse(result=OnboardingStepResult(
        done=False, current_step=2, project_id=bl_id, message="项目已创建，接着填关键词"
    ))


@router.post("/onboarding/keywords", response_model=ApiResponse[OnboardingStepResult])
def onboarding_add_keywords(
    data: OnboardingKeywordsRequest,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """第二步：批量加关键词，一行一个，重复自动跳过"""
    bl_id = _project_id(db, ctx)

    created, skipped = [], []
    for raw in data.keywords:
        kw = (raw or '').strip()
        if not kw:
            continue
        if db.execute(
            text("SELECT id FROM keywords WHERE business_line_id = :bl AND keyword = :kw"),
            {"bl": bl_id, "kw": kw},
        ).fetchone():
            skipped.append(kw)
            continue
        db.execute(
            text("""
                INSERT INTO keywords (tenant_id, business_line_id, keyword, priority, status)
                VALUES (:tid, :bl, :kw, :pri, 1)
            """),
            {"tid": ctx.tenant_id, "bl": bl_id, "kw": kw, "pri": data.priority},
        )
        created.append(kw)

    if not created:
        raise HTTPException(
            status_code=400,
            detail="没有新增任何关键词" + ("，填的可能都重复了" if skipped else ""),
        )
    db.commit()
    _advance(db, ctx.tenant_id, step=3)
    return ApiResponse(result=OnboardingStepResult(
        done=False, current_step=3, project_id=bl_id,
        message=f"已添加 {len(created)} 个关键词" + (f"，跳过重复 {len(skipped)} 个" if skipped else ""),
    ))


@router.post("/onboarding/script", response_model=ApiResponse[OnboardingStepResult])
def onboarding_pick_script(
    data: OnboardingScriptRequest,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """第三步：选话术。选中的是预置模板时先复制到本项目再激活"""
    bl_id = _project_id(db, ctx)

    tpl = db.execute(
        text("""
            SELECT * FROM prompt_templates
            WHERE id = :id AND ((business_line_id = :bl AND tenant_id = :tid) OR (is_preset = 1 AND tenant_id = 1))
        """),
        {"id": data.template_id, "bl": bl_id, "tid": ctx.tenant_id},
    ).fetchone()
    if not tpl:
        raise HTTPException(status_code=404, detail="话术模板不存在")

    target_id = tpl.id
    if tpl.business_line_id != bl_id:
        exists = db.execute(
            text("SELECT id FROM prompt_templates WHERE business_line_id = :bl AND name = :n"),
            {"bl": bl_id, "n": tpl.name},
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
                    "bl": bl_id,
                    "code": f"{tpl.template_code}-c{bl_id}",
                    "name": tpl.name,
                    "content": tpl.template_content,
                },
            )
            target_id = cursor.lastrowid

    db.execute(
        text("UPDATE prompt_templates SET is_active = 0 WHERE business_line_id = :bl AND tenant_id = :tid"),
        {"bl": bl_id, "tid": ctx.tenant_id},
    )
    db.execute(
        text("UPDATE prompt_templates SET is_active = 1, status = 1 WHERE id = :id"),
        {"id": target_id},
    )
    db.commit()
    _advance(db, ctx.tenant_id, step=4)
    return ApiResponse(result=OnboardingStepResult(
        done=False, current_step=4, project_id=bl_id, message="话术已启用，可以启动任务了"
    ))


@router.post("/onboarding/launch", response_model=ApiResponse[OnboardingStepResult])
def onboarding_launch(
    data: OnboardingLaunchRequest,
    ctx: TenantContext = Depends(require_role('admin', 'operator')),
    db: Session = Depends(get_db),
):
    """第四步：建任务并直接入队，走完引导时客户手里已经有一个在跑的任务"""
    bl_id = _project_id(db, ctx)
    bl = db.execute(
        text("SELECT * FROM business_lines WHERE id = :id AND tenant_id = :tid"),
        {"id": bl_id, "tid": ctx.tenant_id},
    ).fetchone()

    limit = max(1, min(int(data.limit or 240), 1000))
    task_config, total, kw_count = build_scrape_task_config(db, bl_id, limit)

    cursor = db.execute(
        text("""
            INSERT INTO task_executions
                (tenant_id, task_name, task_type, business_line_id, status, task_config,
                 total_items, pending_items)
            VALUES (:tid, :name, 'scrape', :bl, 'queued', :cfg, :total, :total)
        """),
        {
            "tid": ctx.tenant_id,
            "name": f"采集-{bl.name}",
            "bl": bl_id,
            "cfg": task_config,
            "total": total,
        },
    )
    task_id = cursor.lastrowid
    db.execute(
        text("INSERT INTO task_logs (task_id, log_level, message) VALUES (:t, 'info', :msg)"),
        {"t": task_id, "msg": f"任务已加入执行队列，共 {kw_count} 个关键词，预计采集 {total} 条"},
    )
    db.commit()

    _advance(db, ctx.tenant_id, step=TOTAL_STEPS, done=True)
    return ApiResponse(result=OnboardingStepResult(
        done=True, current_step=TOTAL_STEPS, project_id=bl_id,
        message="任务已提交，去任务中心看进度",
    ))


@router.post("/onboarding/skip", response_model=ApiResponse[OnboardingStepResult])
def onboarding_skip(ctx: TenantContext = Depends(require_role('admin', 'operator')), db: Session = Depends(get_db)):
    """跳过引导。之后想再走，从项目中心照常建项目即可"""
    _advance(db, ctx.tenant_id, done=True)
    return ApiResponse(result=OnboardingStepResult(done=True, current_step=TOTAL_STEPS, message="已跳过引导"))


# ---------------- 内部函数 ----------------

def _tenant(db: Session, tenant_id: int):
    row = db.execute(text("SELECT * FROM tenants WHERE id = :tid"), {"tid": tenant_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="租户不存在")
    return row


def _current_step(tenant) -> int:
    """当前该做第几步：已完成直接返回最后一步"""
    if tenant.onboarding_done:
        return TOTAL_STEPS
    step = int(tenant.onboarding_step or 1)
    if not tenant.onboarding_project_id:
        return 1
    return min(max(step, 1), TOTAL_STEPS)


def _step_items(current: int, done: bool) -> list:
    items = []
    for idx, (key, title, desc) in enumerate(STEP_DEFS, start=1):
        items.append(OnboardingStepItem(
            index=idx, key=key, title=title, desc=desc,
            done=done or idx < current,
        ))
    return items


def _platforms(db: Session) -> list:
    from src.api.schemas.portal.onboarding import PlatformOption

    rows = db.execute(
        text("SELECT id, name, code FROM platforms WHERE status = 1 ORDER BY id ASC")
    ).fetchall()
    return [PlatformOption(id=r.id, name=r.name, code=r.code) for r in rows]


def _presets(db: Session) -> list:
    rows = db.execute(
        text("""
            SELECT id, name, template_content FROM prompt_templates
            WHERE is_preset = 1 AND tenant_id = 1
            ORDER BY id ASC
        """)
    ).fetchall()
    return [
        PresetScriptOption(id=r.id, name=r.name, preview=(r.template_content or '')[:80])
        for r in rows
    ]


def _project_id(db: Session, ctx: TenantContext) -> int:
    """取引导项目。项目被删了就退到最近建的一个，还没有才报错"""
    tenant = _tenant(db, ctx.tenant_id)
    if tenant.onboarding_project_id:
        exists = db.execute(
            text("SELECT id FROM business_lines WHERE id = :id AND tenant_id = :tid"),
            {"id": tenant.onboarding_project_id, "tid": ctx.tenant_id},
        ).fetchone()
        if exists:
            return int(tenant.onboarding_project_id)

    row = db.execute(
        text("""
            SELECT id FROM business_lines
            WHERE tenant_id = :tid AND code != '__presets__'
            ORDER BY id DESC LIMIT 1
        """),
        {"tid": ctx.tenant_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="先完成第一步，创建一个项目")
    _advance(db, ctx.tenant_id, project_id=row.id)
    return int(row.id)


def _advance(db: Session, tenant_id: int, step: int = None, project_id: int = None, done: bool = False):
    """推进引导态。只往前不回退，避免重复提交把进度打回去"""
    sets = ["updated_at = CURRENT_TIMESTAMP"]
    params: dict = {"tid": tenant_id}
    if project_id is not None:
        sets.append("onboarding_project_id = :pid")
        params["pid"] = project_id
    if step is not None:
        sets.append("onboarding_step = MAX(COALESCE(onboarding_step, 1), :step)")
        params["step"] = step
    if done:
        sets.append("onboarding_done = 1")
    db.execute(text(f"UPDATE tenants SET {', '.join(sets)} WHERE id = :tid"), params)
    db.commit()
