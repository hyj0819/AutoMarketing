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
        for mk in ['dashboard', 'tasks', 'data', 'config', 'config_platforms', 'project', 'project_business_lines', 'project_keywords', 'project_prompt_templates', 'stats']:
            conn.execute(sa_text(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (:rid, :mk)"
            ), {"rid": op_role[0], "mk": mk})

    # viewer 角色菜单权限
    cursor = conn.execute(sa_text("SELECT id FROM roles WHERE role_code = 'viewer'"))
    viewer_role = cursor.fetchone()
    if viewer_role:
        for mk in ['dashboard', 'tasks', 'data', 'stats']:
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
