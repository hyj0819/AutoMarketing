"""
SQLite 数据库初始化脚本
"""

import sqlite3
import hashlib
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "automarketing.db"


def create_tables(conn: sqlite3.Connection):
    """创建所有数据表"""
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platforms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            icon TEXT,
            reach_strategy VARCHAR(30) DEFAULT 'dm',
            status INTEGER DEFAULT 1,
            config TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS business_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            code VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            status INTEGER DEFAULT 1,
            config TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (platform_id) REFERENCES platforms(id),
            UNIQUE(platform_id, code)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_line_id INTEGER NOT NULL,
            keyword VARCHAR(200) NOT NULL,
            status INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_line_id) REFERENCES business_lines(id),
            UNIQUE(business_line_id, keyword)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider VARCHAR(50) NOT NULL,
            model_name VARCHAR(100) NOT NULL,
            api_key_encrypted TEXT NOT NULL,
            base_url VARCHAR(500),
            max_tokens INTEGER DEFAULT 2000,
            temperature INTEGER DEFAULT 70,
            top_p INTEGER DEFAULT 90,
            extra_params TEXT,
            is_active INTEGER DEFAULT 0,
            status INTEGER DEFAULT 1,
            description VARCHAR(500),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider, model_name)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_line_id INTEGER NOT NULL,
            template_code VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            template_content TEXT NOT NULL,
            variables TEXT,
            version INTEGER DEFAULT 1,
            status INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_line_id) REFERENCES business_lines(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            business_line_id INTEGER NOT NULL,
            platform_user_id VARCHAR(200) NOT NULL,
            username VARCHAR(200),
            profile_url VARCHAR(500),
            is_author INTEGER DEFAULT 0,
            contact_status VARCHAR(20) DEFAULT 'pending',
            contact_attempts INTEGER DEFAULT 0,
            last_contact_at DATETIME,
            notes TEXT,
            metadata TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (platform_id) REFERENCES platforms(id),
            FOREIGN KEY (business_line_id) REFERENCES business_lines(id),
            UNIQUE(platform_id, platform_user_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            business_line_id INTEGER NOT NULL,
            content_type VARCHAR(20) NOT NULL,
            content_id VARCHAR(200) NOT NULL,
            content_url VARCHAR(500) NOT NULL,
            title VARCHAR(500),
            content_text TEXT,
            author_id VARCHAR(200),
            author_name VARCHAR(200),
            engagement_stats TEXT,
            ai_analysis_result TEXT,
            source_keyword VARCHAR(200),
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (platform_id) REFERENCES platforms(id),
            FOREIGN KEY (business_line_id) REFERENCES business_lines(id),
            UNIQUE(platform_id, content_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type VARCHAR(50) NOT NULL,
            business_line_id INTEGER NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            total_items INTEGER DEFAULT 0,
            success_items INTEGER DEFAULT 0,
            failed_items INTEGER DEFAULT 0,
            start_time DATETIME,
            end_time DATETIME,
            error_message TEXT,
            execution_log TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_line_id) REFERENCES business_lines(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name VARCHAR(100) NOT NULL,
            platform_id INTEGER NOT NULL,
            browser_id VARCHAR(100),
            status INTEGER DEFAULT 1,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (platform_id) REFERENCES platforms(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_configs (
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
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type VARCHAR(50) NOT NULL,
            operator VARCHAR(100),
            target_type VARCHAR(50),
            target_id INTEGER,
            operation_detail TEXT,
            ip_address VARCHAR(50),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
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
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_code VARCHAR(50) UNIQUE NOT NULL,
            role_name VARCHAR(50) NOT NULL,
            description VARCHAR(200),
            status INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
            UNIQUE(user_id, role_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS role_menus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id INTEGER NOT NULL,
            menu_key VARCHAR(100) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
            UNIQUE(role_id, menu_key)
        )
    """)
    
    conn.commit()


def create_indexes(conn: sqlite3.Connection):
    """创建索引"""
    cursor = conn.cursor()
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_contacts_business_status ON contacts(business_line_id, contact_status)",
        "CREATE INDEX IF NOT EXISTS idx_contacts_last_contact ON contacts(last_contact_at)",
        "CREATE INDEX IF NOT EXISTS idx_contents_business_type ON contents(business_line_id, content_type)",
        "CREATE INDEX IF NOT EXISTS idx_contents_source_keyword ON contents(source_keyword)",
        "CREATE INDEX IF NOT EXISTS idx_task_executions_status ON task_executions(status)",
        "CREATE INDEX IF NOT EXISTS idx_task_executions_business ON task_executions(business_line_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_keywords_business ON keywords(business_line_id)",
        "CREATE INDEX IF NOT EXISTS idx_prompts_business ON prompt_templates(business_line_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_models_provider ON ai_models(provider)",
        "CREATE INDEX IF NOT EXISTS idx_ai_models_active ON ai_models(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform_id)",
        "CREATE INDEX IF NOT EXISTS idx_operation_logs_type ON operation_logs(operation_type)",
        "CREATE INDEX IF NOT EXISTS idx_operation_logs_created ON operation_logs(created_at)",
        # 统计分析优化索引
        "CREATE INDEX IF NOT EXISTS idx_contacts_created_at ON contacts(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_contents_scraped_at ON contents(scraped_at)",
        "CREATE INDEX IF NOT EXISTS idx_contacts_last_contact_at ON contacts(last_contact_at)",
        "CREATE INDEX IF NOT EXISTS idx_contacts_status_created ON contacts(contact_status, created_at)",
    ]
    
    for index_sql in indexes:
        cursor.execute(index_sql)
    
    conn.commit()


def init_base_data(conn: sqlite3.Connection):
    """初始化基础数据"""
    cursor = conn.cursor()
    
    platforms = [
        ('tiktok', 'TikTok', '全球领先的短视频创意社区，助力品牌出海与海外用户触达', '/uploads/platforms/tiktok.png', 'dm'),
        ('xiaohongshu', '小红书', '生活方式分享平台，汇聚真实用户口碑与消费决策内容', '/uploads/platforms/xiaohongshu.png', 'dm'),
        ('douyin', '抖音', '国内领先的短视频平台，覆盖海量用户与丰富的内容生态', '/uploads/platforms/douyin.png', 'comment_reply'),
    ]
    
    cursor.executemany(
        "INSERT OR IGNORE INTO platforms (code, name, description, icon, reach_strategy) VALUES (?, ?, ?, ?, ?)",
        platforms
    )
    
    cursor.execute("""
        INSERT OR IGNORE INTO ai_models (provider, model_name, api_key_encrypted, base_url, max_tokens, temperature, top_p, is_active, status, description)
        VALUES ('deepseek', 'deepseek-chat', '', 'https://api.deepseek.com/v1', 2000, 70, 90, 0, 1, 'DeepSeek 聊天模型 - 默认配置，需填写 API Key 后激活')
    """)
    
    cursor.execute("""
        INSERT OR IGNORE INTO ai_models (provider, model_name, api_key_encrypted, base_url, max_tokens, temperature, top_p, is_active, status, description)
        VALUES ('openai', 'gpt-4o', '', 'https://api.openai.com/v1', 8192, 70, 90, 0, 1, 'OpenAI GPT-4o - 需填写 API Key')
    """)
    
    # 初始化系统参数（风控配置）
    system_configs = [
        ('risk_control', 'message_send_interval_min', '5', 'number', '私信发送最小间隔(分钟)', '两条私信之间的最短等待时间', 1),
        ('risk_control', 'message_send_interval_max', '15', 'number', '私信发送最大间隔(分钟)', '两条私信之间的最长等待时间', 2),
        ('risk_control', 'message_daily_limit', '100', 'number', '每日发送上限(条/账号)', '单个账号每天最多发送的私信数', 3),
        ('risk_control', 'message_batch_limit', '50', 'number', '单次任务发送上限(条)', '单个任务最多发送的私信数', 4),
        ('risk_control', 'reply_interval_min', '3', 'number', '评论回复最小间隔(秒)', '两条评论回复之间的最短等待', 5),
        ('risk_control', 'reply_interval_max', '10', 'number', '评论回复最大间隔(秒)', '两条评论回复之间的最长等待', 6),
        ('ai', 'deepseek_model', 'deepseek-chat', 'string', 'DeepSeek 模型名称', 'DeepSeek API 使用的模型名称', 1),
        ('ai', 'message_max_length', '200', 'number', '私信最大字数', 'AI 生成私信的最大字符数', 2),
        ('worker', 'headless', 'false', 'boolean', '无头模式', '浏览器是否在后台运行，开启后不弹出 Chrome 窗口', 1),
        ('worker', 'poll_interval', '3', 'number', '轮询间隔(秒)', 'Worker 检查新任务的间隔时间', 2),
        ('worker', 'comment_scroll_pause', '2', 'number', '评论滚动间隔(秒)', '爬取评论时滚动暂停的等待时间', 3),
    ]
    for group, key, value, vtype, label, desc, sort in system_configs:
        cursor.execute(
            "INSERT OR IGNORE INTO system_configs (config_group, config_key, config_value, value_type, label, description, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (group, key, value, vtype, label, desc, sort)
        )

    # 初始化内置角色
    roles = [
        ('admin', '超级管理员', '拥有所有权限'),
        ('operator', '普通用户', '拥有日常操作权限'),
        ('viewer', '只读用户', '仅拥有查看权限'),
    ]
    for role_code, role_name, desc in roles:
        cursor.execute(
            "INSERT OR IGNORE INTO roles (role_code, role_name, description) VALUES (?, ?, ?)",
            (role_code, role_name, desc)
        )
    
    # 为 admin 角色分配所有菜单权限
    cursor.execute("SELECT id FROM roles WHERE role_code = 'admin'")
    admin_role = cursor.fetchone()
    if admin_role:
        all_menu_keys = [
            'dashboard', 'tasks', 'data',
            'config', 'config_platforms', 'config_ai_models',
            'project', 'project_business_lines', 'project_keywords', 'project_prompt_templates',
            'stats',
            'system', 'system_users', 'system_roles', 'system_operation_logs', 'system_configs',
        ]
        for mk in all_menu_keys:
            cursor.execute(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (?, ?)",
                (admin_role[0], mk)
            )
    
    # 为 operator 角色分配操作权限
    cursor.execute("SELECT id FROM roles WHERE role_code = 'operator'")
    op_role = cursor.fetchone()
    if op_role:
        op_menu_keys = [
            'dashboard', 'tasks', 'data',
            'config', 'config_platforms',
            'project', 'project_business_lines', 'project_keywords', 'project_prompt_templates',
            'stats',
        ]
        for mk in op_menu_keys:
            cursor.execute(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (?, ?)",
                (op_role[0], mk)
            )
    
    # 为 viewer 角色分配只读权限
    cursor.execute("SELECT id FROM roles WHERE role_code = 'viewer'")
    viewer_role = cursor.fetchone()
    if viewer_role:
        viewer_menu_keys = [
            'dashboard', 'tasks', 'data', 'stats',
        ]
        for mk in viewer_menu_keys:
            cursor.execute(
                "INSERT OR IGNORE INTO role_menus (role_id, menu_key) VALUES (?, ?)",
                (viewer_role[0], mk)
            )
    
    # 初始化默认 admin 用户 (密码: admin123)
    import bcrypt
    password_hash = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
    cursor.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, real_name, email, status) VALUES (?, ?, ?, ?, ?)",
        ('admin', password_hash, '系统管理员', 'admin@automarketing.com', 1)
    )
    # 将 admin 用户关联到 admin 角色
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    admin_user = cursor.fetchone()
    if admin_user and admin_role:
        cursor.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (admin_user[0], admin_role[0])
        )
    
    conn.commit()


def main():
    """主函数"""
    if DB_PATH.exists():
        print(f"数据库已存在: {DB_PATH}")
        response = input("是否删除并重新创建? (y/N): ")
        if response.lower() != 'y':
            print("取消初始化")
            return
        DB_PATH.unlink()
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        print("创建数据表...")
        create_tables(conn)
        print("创建索引...")
        create_indexes(conn)
        print("初始化基础数据...")
        init_base_data(conn)
        print(f"数据库初始化完成: {DB_PATH}")
    except Exception as e:
        print(f"初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
