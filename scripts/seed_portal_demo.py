"""
门户演示数据种子脚本

造一个示例租户「明川照明」，把原型里的数字落成真实数据：
采集 5,860 → 线索 2,140 → 已触达 1,284 → 已回复 149 → 成交 7 单 ¥86,400

用法：
    python scripts/seed_portal_demo.py            # 已存在则跳过
    python scripts/seed_portal_demo.py --reset    # 删除旧演示数据后重建

登录：zhoumin@mingchuan-light.com / mingchuan2026
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bcrypt
from sqlalchemy import text as sa_text

from src.core.database import get_engine

SEED = 20261007
TENANT_CODE = 'mingchuan'
TENANT_NAME = '明川照明'
PLAN = 'growth'

NOW = datetime.now()
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
PERIOD_START = (TODAY - timedelta(days=22)).strftime('%Y-%m-%d')
PERIOD_END = (TODAY + timedelta(days=8)).strftime('%Y-%m-%d')

# 采集内容 / 线索 / 已触达 / 已回复 / 成交 / 丢单
CONTENTS_TOTAL = 5860
LEADS_TOTAL = 2140
REACH_TOTAL = 1284
REPLY_TOTAL = 149
WON_TOTAL = 7
LOST_TOTAL = 41

# 项目：名称、平台代号、状态、本月线索数、启用话术
PROJECTS = [
    ('小红书 · 工装照明需求', 'xiaohongshu', 1, 1020, '询价引导 · 标准版 v3', [
        ('办公室灯光改造', 2, 654),
        ('无主灯设计怎么做', 2, 315),
        ('厂房照明改造', 1, 236),
        ('商铺照明设计', 1, 195),
        ('灯具批发 工装', 1, 158),
        ('线性灯 安装', 1, 61),
    ]),
    ('抖音 · 店铺灯具采购', 'douyin', 0, 486, '样品寄送 v2', [
        ('店铺灯具采购', 2, 260),
        ('直播间灯光布置', 1, 145),
        ('餐饮灯 推荐', 1, 81),
    ]),
    ('知乎 · 无主灯设计', 'zhihu', 1, 412, '方案咨询 v1', [
        ('客厅不装主灯', 2, 210),
        ('层高 2.7 灯光', 1, 122),
        ('无主灯 预算', 1, 80),
    ]),
    ('小红书 · 家装补光改造', 'xiaohongshu', 1, 222, '询价引导 · 家装版 v1', [
        ('家装补光改造', 2, 130),
        ('卧室灯 怎么选', 1, 92),
    ]),
]

# 话术：模板名、触达量、回复数（合计 1,284 / 149）
SCRIPT_PLAN = [
    ('询价引导 · 标准版 v3', 624, 93),
    ('样品寄送 v2', 294, 30),
    ('明川 · 展厅版 v1', 186, 15),
    ('方案咨询 v1', 118, 8),
    ('询价引导 · 家装版 v1', 62, 3),
]

# 成交金额（合计 ¥86,400，7 单；其中 12,800 + 10,800 落在今天）
WON_AMOUNTS = [12800, 10800, 15000, 14200, 13800, 12800, 7000]

# 丢单原因分布（合计 41）
LOST_REASONS = ['no_need'] * 14 + ['price'] * 11 + ['bought_other'] * 8 + ['no_response'] * 5 + ['mistake'] * 3

USERNAMES = ['张工_工装', '设计狗阿May', '王工_厂房', '杭州店铺装修', '展厅老陈', '灯具小王', '小鹿乱撞',
             '装修小分队', '灯光设计师Leo', '厂房改造老李', '餐饮空间笔记', '家装日记', '采购阿珍',
             '工装预算员', '无主灯爱好者', '直播间搭建', '项目经理阿凯', '建材市场老周']

COMMENTS = [
    '我们办公室 800 平要改造，有没有做线性灯的？最好能连工位一起排，别太刺眼。',
    '无主灯怎么做才不压层高？层高只有 2.7，怕压抑。',
    '厂房照明改造大概多少钱一平，两千平能做吗',
    '店铺射灯一般多少瓦一平？我这 60 平，怕太亮也怕太暗。',
    '1200 平的展厅，预算有限，先给个大概方案',
    '批发价多少，量大，走量价给我一个',
    '客厅不装主灯会不会太暗啊，家里有老人',
    '直播间灯光怎么布才不反光？镜头里老是有亮斑。',
    '家装补光要注意什么，卧室和书房都想改',
    '射灯间距到底多少合适，网上说法差太多了',
]

TASK_ROWS = [
    # 名称, 项目序号, 类型, 状态, 总数, 成功, 失败, 进度, 错误
    ('采集 + 触达 · 小红书工装', 0, 'scrape', 'running', 240, 126, 9, 62, None),
    ('采集 · 知乎无主灯', 2, 'scrape', 'queued', 180, 0, 0, 0, None),
    ('采集 + 触达 · 家装补光', 3, 'scrape', 'queued', 240, 0, 0, 0, None),
    ('采集 + 触达 · 小红书工装', 0, 'reach', 'failed', 240, 38, 3, 17, '账号登录态失效，请重新接入账号'),
    ('采集 · 知乎无主灯', 2, 'scrape', 'failed', 180, 0, 0, 0, '采集超时（超过 30 分钟未完成）'),
    ('采集 · 抖音店铺', 1, 'scrape', 'success', 240, 240, 0, 100, None),
    ('采集 + 触达 · 小红书工装', 0, 'reach', 'success', 120, 118, 2, 100, None),
    ('采集 · 知乎无主灯', 2, 'scrape', 'success', 180, 180, 0, 100, None),
]


def rand_dt(start_days_ago: int, end_days_ago: int = 1) -> str:
    """取一个历史随机时间。默认至少 1 天前，今天的数据由 build_today_highlights 单独铺，避免重复计入"""
    delta = random.uniform(max(end_days_ago, 1), start_days_ago)
    return (NOW - timedelta(days=delta)).strftime('%Y-%m-%d %H:%M:%S')


def today_at(hour: int, minute: int = 0) -> str:
    return TODAY.replace(hour=hour, minute=minute).strftime('%Y-%m-%d %H:%M:%S')


def reset(conn):
    print('清理旧的演示数据…')
    tid = conn.execute(sa_text("SELECT id FROM tenants WHERE code = :c"), {"c": TENANT_CODE}).fetchone()
    if not tid:
        return
    tid = tid[0]
    # 先清子表（外键开着，顺序不能反）
    conn.execute(
        sa_text("DELETE FROM contact_interactions WHERE contact_id IN (SELECT id FROM contacts WHERE tenant_id = :tid)"),
        {"tid": tid},
    )
    conn.execute(
        sa_text("DELETE FROM lead_status_logs WHERE contact_id IN (SELECT id FROM contacts WHERE tenant_id = :tid)"),
        {"tid": tid},
    )
    conn.execute(
        sa_text("DELETE FROM task_logs WHERE task_id IN (SELECT id FROM task_executions WHERE tenant_id = :tid)"),
        {"tid": tid},
    )
    for table in ('contacts', 'contents', 'task_executions', 'keywords', 'prompt_templates',
                  'business_lines', 'accounts', 'tenant_members', 'tenant_invitations'):
        conn.execute(sa_text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tid})
    conn.execute(sa_text("DELETE FROM portal_accounts WHERE email LIKE '%@mingchuan-light.com'"))
    conn.execute(sa_text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    conn.commit()


def ensure_platforms(conn) -> dict:
    for code, name, desc in [
        ('xiaohongshu', '小红书', '生活方式平台，装修与采购提问集中'),
        ('douyin', '抖音', '短视频平台，评论量大'),
        ('zhihu', '知乎', '问答社区，决策周期长但质量高'),
    ]:
        conn.execute(
            sa_text("INSERT OR IGNORE INTO platforms (code, name, description, reach_strategy, status) "
                    "VALUES (:c, :n, :d, 'dm', 1)"),
            {"c": code, "n": name, "d": desc},
        )
    conn.commit()
    return {r[1]: r[0] for r in conn.execute(sa_text("SELECT id, code FROM platforms")).fetchall()}


def build_tenant(conn, reset_flag: bool):
    if reset_flag:
        reset(conn)
    exists = conn.execute(sa_text("SELECT id FROM tenants WHERE code = :c"), {"c": TENANT_CODE}).fetchone()
    if exists:
        print(f'演示租户已存在（id={exists[0]}），跳过。要重建请加 --reset')
        sys.exit(0)

    cur = conn.execute(
        sa_text("""
            INSERT INTO tenants (code, name, plan_code, status, quota_reach, quota_ai_calls, quota_seats,
                                 period_start, period_end, contact_name, contact_email)
            VALUES (:c, :n, :p, 1, 2000, 6000, 5, :ps, :pe, '周敏', 'zhoumin@mingchuan-light.com')
        """),
        {"c": TENANT_CODE, "n": TENANT_NAME, "p": PLAN, "ps": PERIOD_START, "pe": PERIOD_END},
    )
    tenant_id = cur.lastrowid

    pwd = bcrypt.hashpw('mingchuan2026'.encode(), bcrypt.gensalt()).decode()
    members = [
        ('zhoumin@mingchuan-light.com', '周敏', 'admin'),
        ('lizhe@mingchuan-light.com', '李哲', 'operator'),
        ('wangqian@mingchuan-light.com', '王倩', 'viewer'),
    ]
    for email, real_name, role in members:
        cur = conn.execute(
            sa_text("""
                INSERT OR IGNORE INTO portal_accounts (email, password_hash, real_name, status, email_verified)
                VALUES (:e, :p, :rn, 1, 1)
            """),
            {"e": email, "p": pwd, "rn": real_name},
        )
        account_id = cur.lastrowid
        if not account_id:
            account_id = conn.execute(
                sa_text("SELECT id FROM portal_accounts WHERE email = :e"), {"e": email}
            ).fetchone()[0]
        conn.execute(
            sa_text("INSERT OR IGNORE INTO tenant_members (tenant_id, account_id, role, status) VALUES (:t, :a, :r, 1)"),
            {"t": tenant_id, "a": account_id, "r": role},
        )
    conn.commit()
    print(f'租户 {TENANT_NAME} 建立完成（id={tenant_id}）')
    return tenant_id


def build_projects(conn, tenant_id: int, platform_ids: dict):
    """建项目、关键词、话术模板、账号"""
    presets = conn.execute(
        sa_text("SELECT id, name, template_content, template_code FROM prompt_templates WHERE is_preset = 1 AND tenant_id = 1")
    ).fetchall()
    preset_map = {r[1]: r for r in presets}
    default_preset = presets[0] if presets else None

    accounts = [('@明川照明官方', 'xiaohongshu'), ('@明川照明-李工', 'douyin'), ('@明川设计笔记', 'zhihu')]
    account_ids = []
    for name, code in accounts:
        cur = conn.execute(
            sa_text("INSERT INTO accounts (tenant_id, account_name, platform_id, status, notes) VALUES (:t, :n, :p, 1, '演示账号')"),
            {"t": tenant_id, "n": name, "p": platform_ids[code]},
        )
        account_ids.append(cur.lastrowid)

    project_ids, template_ids = [], {}
    for idx, (name, platform, status, _lead_count, active_script, keywords) in enumerate(PROJECTS):
        cur = conn.execute(
            sa_text("""
                INSERT INTO business_lines (tenant_id, platform_id, code, name, status, config)
                VALUES (:t, :p, :c, :n, :s, '{}')
            """),
            {"t": tenant_id, "p": platform_ids[platform], "c": f"mc-{idx + 1}", "n": name, "s": status},
        )
        bl_id = cur.lastrowid
        project_ids.append(bl_id)

        for kw, priority, _w in keywords:
            conn.execute(
                sa_text("INSERT INTO keywords (tenant_id, business_line_id, keyword, priority, status) VALUES (:t, :bl, :k, :p, 1)"),
                {"t": tenant_id, "bl": bl_id, "k": kw, "p": priority},
            )

        # 项目自带模板：复制预置库 + 一个客户自定义版本
        for preset in presets:
            conn.execute(
                sa_text("""
                    INSERT INTO prompt_templates
                        (tenant_id, business_line_id, template_code, name, template_content,
                         variables, version, status, is_active, is_preset)
                    VALUES (:t, :bl, :code, :name, :content, '[]', 1, 1, :act, 1)
                """),
                {
                    "t": tenant_id, "bl": bl_id,
                    "code": f"{preset[3]}-mc{bl_id}",
                    "name": preset[1],
                    "content": preset[2],
                    "act": 1 if preset[1] == active_script else 0,
                },
            )

        if idx == 0:
            conn.execute(
                sa_text("""
                    INSERT INTO prompt_templates
                        (tenant_id, business_line_id, template_code, name, template_content,
                         variables, version, status, is_active, is_preset)
                    VALUES (:t, :bl, 'custom-hall', :name, :content, '[]', 1, 1, 0, 0)
                """),
                {
                    "t": tenant_id, "bl": bl_id,
                    "name": '明川 · 展厅版 v1',
                    "content": '您好，看到您在问（关键词）。我们刚做完一个 1200 平的展厅项目，实景图可以发您看看。'
                               '如果您那边面积在 500 平以上，我们可以先出个免费的布灯草图。',
                },
            )
        if idx == 3:
            conn.execute(
                sa_text("""
                    INSERT INTO prompt_templates
                        (tenant_id, business_line_id, template_code, name, template_content,
                         variables, version, status, is_active, is_preset)
                    VALUES (:t, :bl, 'custom-home', :name, :content, '[]', 1, 1, 1, 0)
                """),
                {
                    "t": tenant_id, "bl": bl_id,
                    "name": '询价引导 · 家装版 v1',
                    "content": '看到您在看（关键词）。家装这块我们做得比较多，卧室和书房的补光思路不太一样，'
                               '方便说一下大概面积和层高吗？我可以先给个灯位建议。',
                },
            )

    conn.commit()

    for r in conn.execute(
        sa_text("SELECT id, name FROM prompt_templates WHERE tenant_id = :t"), {"t": tenant_id}
    ).fetchall():
        template_ids.setdefault(r[1], r[0])

    bl_platform = {
        r[0]: r[1] for r in conn.execute(
            sa_text("SELECT id, platform_id FROM business_lines WHERE tenant_id = :t"), {"t": tenant_id}
        ).fetchall()
    }

    print(f'项目 {len(project_ids)} 个，关键词已写入，话术模板 {len(template_ids)} 套')
    return project_ids, template_ids, account_ids, default_preset, bl_platform


def build_contents(conn, tenant_id: int, project_ids: list, bl_platform: dict):
    """采集内容：只填漏斗第一级需要的量，按项目分摊"""
    rows = []
    for i in range(CONTENTS_TOTAL):
        bl = project_ids[i % len(project_ids)]
        rows.append({
            "t": tenant_id,
            "bl": bl,
            "pid": bl_platform[bl],
            "cid": f"demo-content-{i}",
            "url": f"https://example.com/content/{i}",
            "title": f"灯光改造案例 {i}",
            "kw": random.choice([kw for _, _, _, _, _, kws in PROJECTS for kw, _, _ in kws]),
            "ts": rand_dt(22),
        })
    conn.execute(
        sa_text("""
            INSERT OR IGNORE INTO contents
                (tenant_id, platform_id, business_line_id, content_type, content_id, content_url,
                 title, source_keyword, scraped_at, ai_analysis_result)
            VALUES (:t, :pid, :bl, 'video', :cid, :url, :title, :kw, :ts, '高意向')
        """),
        rows,
    )
    conn.commit()
    print(f'采集内容 {CONTENTS_TOTAL} 条')


def build_contacts(conn, tenant_id: int, project_ids: list, template_ids: dict, bl_platform: dict):
    """线索：按项目线索数、关键词权重、话术触达量生成，并落到状态机各档"""
    # 1) 按关键词展开线索
    plan = []
    for p_idx, (name, platform, _st, _lc, _script, keywords) in enumerate(PROJECTS):
        bl = project_ids[p_idx]
        total_w = sum(w for _, _, w in keywords)
        for kw, _p, w in keywords:
            count = round(LEADS_TOTAL * (w / sum(ww for _, _, _, _, _, kws in PROJECTS for _, _, ww in kws)))
            for _ in range(max(1, count)):
                plan.append((bl, kw))

    random.shuffle(plan)
    plan = plan[:LEADS_TOTAL]

    # 2) 触达/回复/成交/丢单的分配
    reach_idx = set(random.sample(range(len(plan)), REACH_TOTAL))
    replied_idx = set(random.sample(sorted(reach_idx), REPLY_TOTAL))
    won_idx = set(random.sample(sorted(replied_idx), WON_TOTAL))
    rest = sorted(replied_idx - won_idx)
    lost_idx = set(random.sample(rest, LOST_TOTAL))

    # 3) 话术归属：按 SCRIPT_PLAN 的触达量分配
    script_assignment = []
    for name, reach, _reply in SCRIPT_PLAN:
        tid = template_ids.get(name)
        script_assignment.extend([tid] * reach)
    random.shuffle(script_assignment)

    won_amounts = WON_AMOUNTS[:]
    lost_reasons = LOST_REASONS[:]
    today_lead_budget = 87

    rows = []
    for i, (bl, kw) in enumerate(plan):
        created = rand_dt(22)
        if i < today_lead_budget:
            created = today_at(random.randint(8, 20), random.randint(0, 59))
        status = 'pending'
        contacted_at, replied_at, won_at = None, None, None
        deal_amount, lost_reason = None, None
        template_id = None

        if i in reach_idx:
            status = 'contacted'
            contacted_at = rand_dt(21)
            template_id = script_assignment.pop() if script_assignment else None
            if i in replied_idx:
                status = random.choice(['replied', 'replied', 'engaged', 'qualified'])
                replied_at = rand_dt(20)
                if i in won_idx:
                    status = 'won'
                    won_at = rand_dt(15)
                    deal_amount = won_amounts.pop() if won_amounts else 12800
                elif i in lost_idx:
                    status = 'lost'
                    lost_reason = lost_reasons.pop() if lost_reasons else 'no_response'

        username = random.choice(USERNAMES)
        rows.append({
            "t": tenant_id,
            "pid": bl_platform[bl],
            "bl": bl,
            "uid": f"demo-user-{i}",
            "name": f"{username}",
            "url": f"https://example.com/u/demo-user-{i}",
            "status": status,
            "meta": json.dumps({
                "source_keyword": kw,
                "comment": random.choice(COMMENTS),
                "ai_level": random.choice(['高意向', '中', '中', '低']),
                "source_title": f"{kw} 相关笔记",
                "source_url": f"https://example.com/content/{random.randint(0, 400)}",
            }, ensure_ascii=False),
            "kw": kw,
            "tpl": template_id,
            "created": created,
            "contacted": contacted_at,
            "replied": replied_at,
            "won": won_at,
            "amount": deal_amount,
            "reason": lost_reason,
            "owner": random.choice(['周敏', '李哲', '王倩']),
        })

    conn.execute(
        sa_text("""
            INSERT OR IGNORE INTO contacts
                (tenant_id, platform_id, business_line_id, platform_user_id, username, profile_url,
                 contact_status, metadata, source_keyword, prompt_template_id, created_at,
                 last_contact_at, replied_at, won_at, deal_amount, lost_reason, owner, contact_attempts)
            VALUES (:t, :pid, :bl, :uid, :name, :url, :status, :meta, :kw, :tpl, :created,
                    :contacted, :replied, :won, :amount, :reason, :owner, 1)
        """),
        rows,
    )
    conn.commit()
    print(f'线索 {len(rows)} 条（已触达 {REACH_TOTAL} / 已回复 {REPLY_TOTAL} / 成交 {WON_TOTAL} / 丢单 {LOST_TOTAL}）')
    return rows


def build_today_highlights(conn, tenant_id: int):
    """今日数据：新增线索 87、已发送 62、回复 9、成交 2 单 ¥23,600

    只改时间戳，不新增记录，保证漏斗与归因的总量不变。
    """
    today_str = TODAY.strftime('%Y-%m-%d')

    # 已发送 62
    conn.execute(
        sa_text("""
            UPDATE contacts SET last_contact_at = :ts
            WHERE tenant_id = :t AND contact_status IN ('contacted','replied','engaged','qualified','won','lost')
              AND id IN (
                SELECT id FROM contacts WHERE tenant_id = :t
                  AND contact_status IN ('contacted','replied','engaged','qualified','won','lost')
                ORDER BY id ASC LIMIT 62
              )
        """),
        {"t": tenant_id, "ts": today_at(11, 20)},
    )
    # 今日新回复 9
    conn.execute(
        sa_text("""
            UPDATE contacts SET replied_at = :ts
            WHERE tenant_id = :t AND contact_status IN ('replied', 'engaged', 'qualified')
              AND id IN (
                SELECT id FROM contacts WHERE tenant_id = :t
                  AND contact_status IN ('replied', 'engaged', 'qualified')
                ORDER BY id ASC LIMIT 9
              )
        """),
        {"t": tenant_id, "ts": today_at(9, 12)},
    )
    # 今日成交 2 单：12,800 + 10,800
    conn.execute(
        sa_text("""
            UPDATE contacts SET won_at = :ts WHERE tenant_id = :t AND contact_status = 'won'
              AND id IN (SELECT id FROM contacts WHERE tenant_id = :t AND deal_amount = 12800 ORDER BY id ASC LIMIT 1)
        """),
        {"t": tenant_id, "ts": today_at(8, 50)},
    )
    conn.execute(
        sa_text("""
            UPDATE contacts SET won_at = :ts WHERE tenant_id = :t AND contact_status = 'won'
              AND id IN (SELECT id FROM contacts WHERE tenant_id = :t AND deal_amount = 10800 ORDER BY id ASC LIMIT 1)
        """),
        {"t": tenant_id, "ts": today_at(10, 20)},
    )
    conn.commit()
    print(f'今日数据已落定（{today_str}）')


def build_tasks(conn, tenant_id: int, project_ids: list, account_ids: list, contacts: list):
    """任务：1 运行中、2 等待中、2 失败、3 成功，并写日志与命中关系"""
    task_ids = []
    for idx, (name, p_idx, ttype, status, total, success, failed, progress, error) in enumerate(TASK_ROWS):
        bl = project_ids[p_idx]
        cfg = json.dumps({"keywords": [kw for kw, _, _ in PROJECTS[p_idx][5]], "demo": True}, ensure_ascii=False)
        start = rand_dt(2) if status in ('running', 'success', 'failed') else None
        end = None
        if status in ('success', 'failed') and start:
            # 耗时取 8~35 分钟，贴近真实采集任务的量级
            start_dt = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
            end = (start_dt + timedelta(minutes=random.randint(8, 35))).strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute(
            sa_text("""
                INSERT INTO task_executions
                    (tenant_id, task_name, task_type, business_line_id, status, task_config,
                     total_items, success_items, failed_items, pending_items, progress,
                     account_id, start_time, end_time, error_message)
                VALUES (:t, :n, :tt, :bl, :st, :cfg, :total, :ok, :bad, :pending, :prog, :acc, :s, :e, :err)
            """),
            {
                "t": tenant_id, "n": name, "tt": ttype, "bl": bl, "st": status, "cfg": cfg,
                "total": total, "ok": success, "bad": failed,
                "pending": max(total - success - failed, 0), "prog": progress,
                "acc": account_ids[p_idx % len(account_ids)], "s": start, "e": end, "err": error,
            },
        )
        task_ids.append(cur.lastrowid)

    conn.commit()

    # 日志：给运行中任务与失败任务各写几条
    running_id, failed_id = task_ids[0], task_ids[3]
    logs = [
        (running_id, 'info', '任务开始 · 队列第 1 位 · 采集上限 240'),
        (running_id, 'info', '加载关键词 7 个，按优先级排序完成'),
        (running_id, 'info', '关键词「办公室灯光改造」开始采集'),
        (running_id, 'info', '采集到 42 条内容，去重后 38 条'),
        (running_id, 'info', 'AI 筛选完成：高意向 9，中 17，低 12'),
        (running_id, 'info', '开始触达 · 话术模板 询价引导 · 标准版 v3'),
        (running_id, 'info', '已发送 12 / 240，成功 11，失败 1'),
        (running_id, 'warn', '账号近 1 小时已发送 43 条，按平台策略自动降速'),
        (running_id, 'error', '用户已注销，跳过（ID 88213）'),
        (running_id, 'info', '关键词「厂房照明改造」命中 23 条，其中高意向 6 条'),
        (running_id, 'info', '已处理 148 / 240 · 成功 126 · 失败 9 · 待处理 13'),
        (failed_id, 'info', '任务开始 · 队列第 1 位'),
        (failed_id, 'warn', '检测到账号登录态失效'),
        (failed_id, 'error', '账号登录态失效，请重新接入账号'),
    ]
    conn.execute(
        sa_text("INSERT INTO task_logs (task_id, log_level, message) VALUES (:t, :l, :m)"),
        [{"t": t, "l": l, "m": m} for t, l, m in logs],
    )

    # 命中关系：运行中任务挂 37 条线索，供任务详情预览
    hit_rows = [{"cid": r["uid"], "tid": running_id} for r in contacts[:37]]
    conn.execute(
        sa_text("""
            INSERT INTO contact_interactions (contact_id, interaction_type, task_execution_id, detail)
            VALUES ((SELECT id FROM contacts WHERE platform_user_id = :cid AND tenant_id = :t), 'scraped', :tid, '演示采集')
        """),
        [{**h, "t": tenant_id} for h in hit_rows],
    )
    conn.commit()
    print(f'任务 {len(task_ids)} 个（1 运行中 / 2 等待中 / 2 失败 / 3 成功）')
    return task_ids


def build_status_logs(conn, tenant_id: int):
    """给成交与丢单线索补一条状态流转记录，供线索详情时间线展示"""
    rows = conn.execute(
        sa_text("""
            SELECT id, contact_status, lost_reason, deal_amount FROM contacts
            WHERE tenant_id = :t AND contact_status IN ('won', 'lost')
        """),
        {"t": tenant_id},
    ).fetchall()
    payload = []
    for r in rows:
        payload.append({
            "cid": r[0], "to": r[1],
            "reason": r[2] if r[1] == 'lost' else None,
            "note": f"成交金额 {int(r[3])}" if r[1] == 'won' else None,
            "op": random.choice(['周敏', '李哲']),
        })
    if payload:
        conn.execute(
            sa_text("""
                INSERT INTO lead_status_logs (contact_id, from_status, to_status, reason, note, operator)
                VALUES (:cid, 'qualified', :to, :reason, :note, :op)
            """),
            payload,
        )
        conn.commit()
    print(f'状态流转记录 {len(payload)} 条')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reset', action='store_true', help='先删除旧的演示数据')
    args = parser.parse_args()

    random.seed(SEED)
    engine = get_engine()
    with engine.connect() as conn:
        tenant_id = build_tenant(conn, args.reset)
        platform_ids = ensure_platforms(conn)
        project_ids, template_ids, account_ids, _, bl_platform = build_projects(conn, tenant_id, platform_ids)
        build_contents(conn, tenant_id, project_ids, bl_platform)
        contacts = build_contacts(conn, tenant_id, project_ids, template_ids, bl_platform)
        build_today_highlights(conn, tenant_id)
        build_tasks(conn, tenant_id, project_ids, account_ids, contacts)
        build_status_logs(conn, tenant_id)

    print('\n完成。登录：zhoumin@mingchuan-light.com / mingchuan2026')
    print(f'结算周期：{PERIOD_START} ~ {PERIOD_END}')


if __name__ == '__main__':
    main()
