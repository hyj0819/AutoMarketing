"""
数据库连接配置
"""

from sqlalchemy import create_engine, event, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import text as sa_text
from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

Base = declarative_base()


def get_database_url() -> str:
    """获取数据库URL"""
    return os.getenv('DATABASE_URL', 'sqlite:///./automarketing.db')


def configure_sqlite_connection(dbapi_connection, connection_record):
    """配置 SQLite 连接优化"""
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.execute('PRAGMA synchronous=NORMAL')
    cursor.execute('PRAGMA cache_size=-16384')
    cursor.execute('PRAGMA mmap_size=1073741824')
    cursor.execute('PRAGMA temp_store=MEMORY')
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()


def get_engine():
    """创建数据库引擎"""
    engine = create_engine(
        get_database_url(),
        connect_args={"check_same_thread": False},
        echo=False
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    return engine


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ContactInteraction(Base):
    """触达历史记录"""
    __tablename__ = 'contact_interactions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey('contacts.id'), nullable=False)
    interaction_type = Column(String(50), nullable=False)  # message_sent/comment_replied/scraped/ai_analyzed
    task_execution_id = Column(Integer, ForeignKey('task_executions.id'), nullable=True)
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    contact = relationship('Contact', backref='interactions')


def init_contact_interactions_table():
    """确保 contact_interactions 表存在"""
    engine = get_engine()
    with engine.connect() as conn:
        cursor = conn.execute(sa_text("SELECT name FROM sqlite_master WHERE type='table' AND name='contact_interactions'"))
        if not cursor.fetchone():
            conn.execute(sa_text("""
                CREATE TABLE contact_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_id INTEGER NOT NULL,
                    interaction_type VARCHAR(50) NOT NULL,
                    task_execution_id INTEGER,
                    detail TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id),
                    FOREIGN KEY (task_execution_id) REFERENCES task_executions(id)
                )
            """))
            conn.commit()


# 启动时确保表存在
init_contact_interactions_table()


def init_user_role_tables():
    """确保 users/roles/user_roles/role_menus 表存在"""
    engine = get_engine()
    with engine.connect() as conn:
        tables = {
            "users": """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    real_name VARCHAR(50),
                    email VARCHAR(100),
                    status INTEGER DEFAULT 1,
                    last_login_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "roles": """
                CREATE TABLE roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_code VARCHAR(50) UNIQUE NOT NULL,
                    role_name VARCHAR(50) NOT NULL,
                    description VARCHAR(200),
                    status INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "user_roles": """
                CREATE TABLE user_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                    UNIQUE(user_id, role_id)
                )
            """,
            "role_menus": """
                CREATE TABLE role_menus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL,
                    menu_key VARCHAR(100) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                    UNIQUE(role_id, menu_key)
                )
            """,
        }
        for table_name, ddl in tables.items():
            cursor = conn.execute(sa_text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
            ), {"name": table_name})
            if not cursor.fetchone():
                conn.execute(sa_text(ddl))
        conn.commit()

        # 初始化内置角色和 admin 用户
        _seed_default_roles_and_admin(conn)


def _seed_default_roles_and_admin(conn):
    """初始化内置角色和默认 admin 用户"""
    import bcrypt

    # 内置角色
    roles = [
        ('admin', '超级管理员', '拥有所有权限'),
        ('operator', '普通用户', '拥有日常操作权限'),
        ('viewer', '只读用户', '仅拥有查看权限'),
    ]
    for role_code, role_name, desc in roles:
        conn.execute(sa_text(
            "INSERT OR IGNORE INTO roles (role_code, role_name, description) VALUES (:rc, :rn, :d)"
        ), {"rc": role_code, "rn": role_name, "d": desc})
    conn.flush() if hasattr(conn, 'flush') else None

    # admin 角色菜单权限
    cursor = conn.execute(sa_text("SELECT id FROM roles WHERE role_code = 'admin'"))
    admin_role = cursor.fetchone()
    if admin_role:
        all_keys = [
            'dashboard', 'tasks', 'data',
            'leads', 'leads_todo', 'leads_queue',
            'config', 'config_platforms', 'config_ai_models',
            'project', 'project_business_lines', 'project_keywords', 'project_prompt_templates',
            'stats',
            'system', 'system_users', 'system_roles', 'system_operation_logs', 'system_configs',
        ]
        for mk in all_keys:
            conn.execute(sa_text(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (:rid, :mk)"
            ), {"rid": admin_role[0], "mk": mk})

    # operator 角色菜单权限
    cursor = conn.execute(sa_text("SELECT id FROM roles WHERE role_code = 'operator'"))
    op_role = cursor.fetchone()
    if op_role:
        for mk in ['dashboard', 'tasks', 'data', 'leads', 'leads_todo', 'leads_queue', 'config', 'config_platforms', 'project', 'project_business_lines', 'project_keywords', 'project_prompt_templates', 'stats']:
            conn.execute(sa_text(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (:rid, :mk)"
            ), {"rid": op_role[0], "mk": mk})

    # viewer 角色菜单权限
    cursor = conn.execute(sa_text("SELECT id FROM roles WHERE role_code = 'viewer'"))
    viewer_role = cursor.fetchone()
    if viewer_role:
        for mk in ['dashboard', 'tasks', 'data', 'leads', 'leads_todo', 'leads_queue', 'stats']:
            conn.execute(sa_text(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (:rid, :mk)"
            ), {"rid": viewer_role[0], "mk": mk})

    # 默认 admin 用户
    cursor = conn.execute(sa_text("SELECT id FROM users WHERE username = 'admin'"))
    admin_user = cursor.fetchone()
    if not admin_user:
        pwd_hash = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        conn.execute(sa_text(
            "INSERT INTO users (username, password_hash, real_name, email, status) VALUES (:u, :p, :rn, :e, :s)"
        ), {"u": "admin", "p": pwd_hash, "rn": "系统管理员", "e": "admin@automarketing.com", "s": 1})
        conn.flush() if hasattr(conn, 'flush') else None
        # 关联 admin 用户到 admin 角色
        cursor = conn.execute(sa_text("SELECT id FROM users WHERE username = 'admin'"))
        admin_user = cursor.fetchone()
        if admin_user and admin_role:
            conn.execute(sa_text(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"
            ), {"uid": admin_user[0], "rid": admin_role[0]})

    conn.commit()


init_user_role_tables()


def migrate_system_configs():
    """迁移 system_configs 表：旧结构 → 新结构（添加 config_group/label/sort_order 等）"""
    engine = get_engine()
    with engine.connect() as conn:
        # 检查旧表是否存在
        cursor = conn.execute(sa_text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_configs'"
        ))
        if not cursor.fetchone():
            # 表不存在，创建新结构
            conn.execute(sa_text("""
                CREATE TABLE system_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_group VARCHAR(50) NOT NULL,
                    config_key VARCHAR(100) NOT NULL,
                    config_value TEXT,
                    value_type VARCHAR(20) DEFAULT 'string',
                    label VARCHAR(200),
                    description TEXT,
                    sort_order INTEGER DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(config_group, config_key)
                )
            """))
            conn.commit()
            _seed_system_configs(conn)
            return

        # 检查是否已有 config_group 列
        cursor = conn.execute(sa_text("PRAGMA table_info(system_configs)"))
        columns = [row[1] for row in cursor.fetchall()]
        if 'config_group' not in columns:
            # 旧表结构，需要迁移
            conn.execute(sa_text("DROP TABLE system_configs"))
            conn.execute(sa_text("""
                CREATE TABLE system_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_group VARCHAR(50) NOT NULL,
                    config_key VARCHAR(100) NOT NULL,
                    config_value TEXT,
                    value_type VARCHAR(20) DEFAULT 'string',
                    label VARCHAR(200),
                    description TEXT,
                    sort_order INTEGER DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(config_group, config_key)
                )
            """))
            _seed_system_configs(conn)

        conn.commit()


def _seed_system_configs(conn):
    """初始化系统参数种子数据"""
    configs = [
        ('risk_control', 'message_send_interval_min', '5', 'number', '私信发送最小间隔(分钟)', '两条私信之间的最短等待时间', 1),
        ('risk_control', 'message_send_interval_max', '15', 'number', '私信发送最大间隔(分钟)', '两条私信之间的最长等待时间', 2),
        ('risk_control', 'message_daily_limit', '100', 'number', '每日发送上限(条/账号)', '单个账号每天最多发送的私信数', 3),
        ('risk_control', 'message_batch_limit', '50', 'number', '单次任务发送上限(条)', '单个任务最多发送的私信数', 4),
        ('risk_control', 'reply_interval_min', '3', 'number', '评论回复最小间隔(秒)', '两条评论回复之间的最短等待', 5),
        ('risk_control', 'reply_interval_max', '10', 'number', '评论回复最大间隔(秒)', '两条评论回复之间的最长等待', 6),
        ('ai', 'deepseek_model', 'deepseek-chat', 'string', 'DeepSeek 模型名称', 'DeepSeek API 使用的模型名称', 1),
        ('ai', 'message_max_length', '200', 'number', '私信最大字数', 'AI 生成私信的最大字符数', 2),
    ]
    for group, key, value, vtype, label, desc, sort in configs:
        conn.execute(sa_text(
            "INSERT OR IGNORE INTO system_configs (config_group, config_key, config_value, value_type, label, description, sort_order) "
            "VALUES (:g, :k, :v, :vt, :l, :d, :s)"
        ), {"g": group, "k": key, "v": value, "vt": vtype, "l": label, "d": desc, "s": sort})


migrate_system_configs()


def migrate_contacts_lead_fields():
    """迁移 contacts 表：补充线索跟进所需字段，并建立状态流转记录表"""
    engine = get_engine()
    with engine.connect() as conn:
        cursor = conn.execute(sa_text("PRAGMA table_info(contacts)"))
        columns = [row[1] for row in cursor.fetchall()]

        new_columns = [
            ("replied_at", "DATETIME"),
            ("quote_amount", "REAL"),
            ("quoted_at", "DATETIME"),
            ("deal_amount", "REAL"),
            ("won_at", "DATETIME"),
            ("lost_reason", "VARCHAR(50)"),
            ("owner", "VARCHAR(50)"),
            ("snooze_until", "DATETIME"),
            ("tags", "TEXT"),
        ]
        for col_name, col_ddl in new_columns:
            if col_name not in columns:
                conn.execute(sa_text(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_ddl}"))

        # 历史状态 converted 统一映射为 won，避免新旧状态并存
        conn.execute(sa_text("UPDATE contacts SET contact_status='won' WHERE contact_status='converted'"))

        conn.execute(sa_text("""
            CREATE TABLE IF NOT EXISTS lead_status_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER NOT NULL,
                from_status VARCHAR(20),
                to_status VARCHAR(20) NOT NULL,
                reason VARCHAR(100),
                note TEXT,
                operator VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (contact_id) REFERENCES contacts(id)
            )
        """))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_lead_status_logs_contact ON lead_status_logs(contact_id, created_at)"
        ))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_contacts_status_owner ON contacts(contact_status, owner)"
        ))
        conn.commit()


migrate_contacts_lead_fields()


def migrate_platforms_reach_strategy():
    """迁移 platforms 表：添加 reach_strategy 列并设置默认值"""
    engine = get_engine()
    with engine.connect() as conn:
        cursor = conn.execute(sa_text("PRAGMA table_info(platforms)"))
        columns = [row[1] for row in cursor.fetchall()]
        if 'reach_strategy' not in columns:
            conn.execute(sa_text(
                "ALTER TABLE platforms ADD COLUMN reach_strategy VARCHAR(30) DEFAULT 'dm'"
            ))
            # 为已有平台设置正确的触达策略
            conn.execute(sa_text(
                "UPDATE platforms SET reach_strategy = 'comment_reply' WHERE code = 'douyin'"
            ))
            conn.commit()


migrate_platforms_reach_strategy()


# ==================== 多租户：租户表与业务表 tenant_id ====================
# 约定：
# 1) 租户 = 一个付费客户公司；所有业务数据挂在 tenant_id 下
# 2) 平台自用数据统一归入默认租户 DEFAULT_TENANT_ID(=1)，自用端行为不变
# 3) 隔离由应用层保证：portal 查询强制带 tenant_id，不依赖前端传参
# 4) SQLite 的 ALTER TABLE 不支持无默认值的 NOT NULL，故先加可空列再回填

DEFAULT_TENANT_ID = 1

# 需要加 tenant_id 的业务表；第二项为可继承租户的业务线外键，None 表示直接归默认租户
TENANT_TABLES = [
    ("business_lines", None),
    ("keywords", "business_line_id"),
    ("prompt_templates", "business_line_id"),
    ("contacts", "business_line_id"),
    ("contents", "business_line_id"),
    ("task_executions", "business_line_id"),
    ("accounts", None),
]

TENANT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_business_lines_tenant ON business_lines(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_keywords_tenant ON keywords(tenant_id, business_line_id)",
    "CREATE INDEX IF NOT EXISTS idx_prompts_tenant ON prompt_templates(tenant_id, business_line_id)",
    "CREATE INDEX IF NOT EXISTS idx_contacts_tenant ON contacts(tenant_id, business_line_id, contact_status)",
    "CREATE INDEX IF NOT EXISTS idx_contents_tenant ON contents(tenant_id, business_line_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_executions_tenant ON task_executions(tenant_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_accounts_tenant ON accounts(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_tenant_members_account ON tenant_members(account_id, status)",
]


def init_tenant_tables():
    """创建租户、门户账号、成员与邀请表，并播种默认租户（幂等）"""
    engine = get_engine()
    with engine.connect() as conn:
        tables = {
            "tenants": """
                CREATE TABLE tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    plan_code VARCHAR(30) DEFAULT 'growth',
                    status INTEGER DEFAULT 1,
                    quota_reach INTEGER DEFAULT 2000,
                    quota_ai_calls INTEGER DEFAULT 6000,
                    quota_seats INTEGER DEFAULT 5,
                    period_start VARCHAR(10),
                    period_end VARCHAR(10),
                    contact_name VARCHAR(50),
                    contact_email VARCHAR(100),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "portal_accounts": """
                CREATE TABLE portal_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    real_name VARCHAR(50),
                    status INTEGER DEFAULT 1,
                    email_verified INTEGER DEFAULT 0,
                    last_login_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "tenant_members": """
                CREATE TABLE tenant_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    role VARCHAR(20) DEFAULT 'operator',
                    status INTEGER DEFAULT 1,
                    visible_scope TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tenant_id, account_id)
                )
            """,
            "tenant_invitations": """
                CREATE TABLE tenant_invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    email VARCHAR(100) NOT NULL,
                    role VARCHAR(20) DEFAULT 'operator',
                    token VARCHAR(64) UNIQUE NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    expires_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """,
        }
        for table_name, ddl in tables.items():
            cursor = conn.execute(sa_text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
            ), {"name": table_name})
            if not cursor.fetchone():
                conn.execute(sa_text(ddl))

        # 默认租户：平台自用。历史数据全部归入该租户
        conn.execute(sa_text(
            "INSERT OR IGNORE INTO tenants (id, code, name, plan_code, status, quota_reach, quota_ai_calls, quota_seats) "
            "VALUES (:id, 'platform', '平台自用', 'internal', 1, 99999999, 99999999, 9999)"
        ), {"id": DEFAULT_TENANT_ID})
        conn.commit()


def migrate_business_tenant_id():
    """为业务表补充 tenant_id 列、回填默认租户并建立租户索引（幂等）"""
    engine = get_engine()
    with engine.connect() as conn:
        for table, _ in TENANT_TABLES:
            cursor = conn.execute(sa_text(f"PRAGMA table_info({table})"))
            columns = [row[1] for row in cursor.fetchall()]
            if not columns:
                continue  # 表不存在时跳过，由 init_db 负责建表
            if "tenant_id" not in columns:
                conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER"))

        # 回填：先定业务线的租户，再让子表从业务线继承，最后兜底默认租户
        conn.execute(sa_text(
            "UPDATE business_lines SET tenant_id = :tid WHERE tenant_id IS NULL"
        ), {"tid": DEFAULT_TENANT_ID})

        for table, fk in TENANT_TABLES:
            if not fk:
                continue
            conn.execute(sa_text(f"""
                UPDATE {table} SET tenant_id = (
                    SELECT bl.tenant_id FROM business_lines bl WHERE bl.id = {table}.{fk}
                )
                WHERE tenant_id IS NULL AND {fk} IS NOT NULL
            """))

        for table, _ in TENANT_TABLES:
            conn.execute(sa_text(
                f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"
            ), {"tid": DEFAULT_TENANT_ID})

        for idx_sql in TENANT_INDEXES:
            conn.execute(sa_text(idx_sql))

        conn.commit()


init_tenant_tables()
migrate_business_tenant_id()


def migrate_contacts_attribution_fields():
    """为 contacts 补充归因字段：来源关键词与触达时使用的话术模板

    看板的「关键词归因排行」与「话术效果对比」依赖这两项，
    没有它们就只能算出触达量，算不出哪个词、哪套话术带来了回复与成交。
    """
    engine = get_engine()
    with engine.connect() as conn:
        cursor = conn.execute(sa_text("PRAGMA table_info(contacts)"))
        columns = [row[1] for row in cursor.fetchall()]
        if not columns:
            return

        for col_name, col_ddl in [
            ("source_keyword", "VARCHAR(200)"),
            ("prompt_template_id", "INTEGER"),
        ]:
            if col_name not in columns:
                conn.execute(sa_text(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_ddl}"))

        # 历史数据：从 metadata JSON 里回挖来源关键词（无 JSON1 扩展时跳过）
        try:
            conn.execute(sa_text("""
                UPDATE contacts
                SET source_keyword = json_extract(metadata, '$.source_keyword')
                WHERE source_keyword IS NULL
                  AND metadata IS NOT NULL
                  AND json_extract(metadata, '$.source_keyword') IS NOT NULL
            """))
        except Exception:
            pass

        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_contacts_source_keyword ON contacts(tenant_id, source_keyword)"
        ))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_contacts_template ON contacts(tenant_id, prompt_template_id)"
        ))
        conn.commit()


migrate_contacts_attribution_fields()


# ==================== 门户新手引导态 ====================
# 引导是租户级的：一个团队只需走一遍，谁先建第一个项目就算这个团队完成到哪一步。
# 存 step 而不是布尔值，是为了用户中途关掉页面后再进来能接着走，不用从头填。

ONBOARDING_STEPS = 4

TENANT_ONBOARDING_COLUMNS = [
    ("onboarding_step", "INTEGER DEFAULT 1"),
    ("onboarding_done", "INTEGER DEFAULT 0"),
    ("onboarding_project_id", "INTEGER"),
]


def migrate_tenant_onboarding():
    """为 tenants 补充新手引导态字段（幂等）

    平台自用租户（默认租户）直接标记完成，避免自用端账号被引导流程拦住。
    """
    engine = get_engine()
    with engine.connect() as conn:
        cursor = conn.execute(sa_text("PRAGMA table_info(tenants)"))
        columns = [row[1] for row in cursor.fetchall()]
        if not columns:
            return  # 表不存在时跳过，由 init_tenant_tables 负责建表

        for col, ddl in TENANT_ONBOARDING_COLUMNS:
            if col not in columns:
                conn.execute(sa_text(f"ALTER TABLE tenants ADD COLUMN {col} {ddl}"))

        conn.execute(sa_text(
            "UPDATE tenants SET onboarding_step = 1 WHERE onboarding_step IS NULL"
        ))
        conn.execute(sa_text(
            "UPDATE tenants SET onboarding_done = 0 WHERE onboarding_done IS NULL"
        ))
        conn.execute(sa_text(
            "UPDATE tenants SET onboarding_done = 1, onboarding_step = :steps WHERE id = :tid"
        ), {"steps": ONBOARDING_STEPS, "tid": DEFAULT_TENANT_ID})
        conn.commit()


migrate_tenant_onboarding()


PRESET_TEMPLATES = [
    (
        "询价引导 · 标准版 v3",
        "您好，看到您在问（关键词）。我们做商用照明方案，800 平左右的办公室改造一般 3 天出图。"
        "可以先发一份同面积段的近期案例给您参考，方便的话加个微信？",
        "先给出可验证的信息，再要联系方式。适合问价格、问方案的评论。",
    ),
    (
        "样品寄送 v2",
        "看到您在找（关键词）。这几款我们有现货，可以寄一套样品给您对比，运费我们出。方便发个收货地址吗？",
        "用实物降低决策门槛。适合明确在找货源的评论。",
    ),
    (
        "方案咨询 v1",
        "您好，我们是做（品类）方案设计的。想先了解一下：面积大概多少、层高多少、有没有已经确定的风格？"
        "我可以先给个大致的布灯思路。",
        "先问需求再报价，适合金额大、周期长的线索。",
    ),
    (
        "先问需求 · 保守版 v2",
        "看到您提到（关键词）。我们这边做过类似的项目，如果您还在选型，我可以把当时踩过的坑整理几条发您，不用急着定。",
        "不带营销动作，平台管控较严时用它更稳妥。",
    ),
]


def seed_preset_templates():
    """播种平台预置话术模板库：客户不用自己写提示词，选一套就能启动

    预置模板挂在平台自用租户下的专用业务线里，门户新建项目时从这里复制一份。
    """
    engine = get_engine()
    with engine.connect() as conn:
        cursor = conn.execute(sa_text("PRAGMA table_info(prompt_templates)"))
        columns = [row[1] for row in cursor.fetchall()]
        if not columns:
            return
        if "is_preset" not in columns:
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN is_preset INTEGER DEFAULT 0"))

        platform_row = conn.execute(
            sa_text("SELECT id FROM platforms ORDER BY id ASC LIMIT 1")
        ).fetchone()
        platform_id = platform_row[0] if platform_row else 1

        conn.execute(sa_text("""
            INSERT OR IGNORE INTO business_lines (tenant_id, platform_id, code, name, status)
            VALUES (1, :pid, '__presets__', '平台预置话术库', 1)
        """), {"pid": platform_id})

        bl = conn.execute(
            sa_text("SELECT id FROM business_lines WHERE code = '__presets__'")
        ).fetchone()
        if not bl:
            conn.commit()
            return

        for idx, (name, content, _desc) in enumerate(PRESET_TEMPLATES, start=1):
            exists = conn.execute(
                sa_text("SELECT id FROM prompt_templates WHERE business_line_id = :bl AND name = :n"),
                {"bl": bl[0], "n": name},
            ).fetchone()
            if exists:
                continue
            conn.execute(
                sa_text("""
                    INSERT INTO prompt_templates
                        (tenant_id, business_line_id, template_code, name, template_content,
                         variables, version, status, is_active, is_preset)
                    VALUES (1, :bl, :code, :name, :content, '[]', 1, 1, 0, 1)
                """),
                {"bl": bl[0], "code": f"preset-{idx}", "name": name, "content": content},
            )
        conn.commit()


seed_preset_templates()
