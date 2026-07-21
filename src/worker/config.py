"""
Worker 配置解析

负责解析：
- Chrome 持久化 profile 目录（业务线 config 优先，其次平台默认常量）
- 无头模式开关（env WORKER_HEADLESS）
- DeepSeek API Key（conf/api_key.json）
- 轮询间隔（env WORKER_POLL_INTERVAL）
"""

import json
import os
from pathlib import Path

# 项目根目录（src/worker/config.py -> 上溯三级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 平台默认 Chrome profile 目录（相对项目根）
PLATFORM_DEFAULT_PROFILE = {
    "tiktok": "chrome_data/Chrome_Bot_Data_TK",
}

API_KEY_FILE = PROJECT_ROOT / "conf" / "api_key.json"


def get_poll_interval() -> int:
    """轮询间隔（秒），默认 3s"""
    try:
        return int(os.getenv("WORKER_POLL_INTERVAL", "3"))
    except ValueError:
        return 3


def is_headless() -> bool:
    """是否无头运行浏览器，默认 True（无头，不打开浏览器窗口）"""
    return os.getenv("WORKER_HEADLESS", "true").strip().lower() in ("1", "true", "yes")


def resolve_chrome_profile(business_line_config: str | None, platform_code: str) -> str:
    """
    解析 Chrome profile 目录，优先级：
    1. business_lines.config.chrome_user_data_dir
    2. 平台默认常量（tiktok -> chrome_data/Chrome_Bot_Data_TK）

    相对路径统一相对项目根解析为绝对路径。
    """
    profile_dir = None

    # 1. 业务线配置优先
    if business_line_config:
        try:
            cfg = json.loads(business_line_config)
            if isinstance(cfg, dict) and cfg.get("chrome_user_data_dir"):
                profile_dir = cfg["chrome_user_data_dir"]
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. 平台默认
    if not profile_dir:
        profile_dir = PLATFORM_DEFAULT_PROFILE.get(platform_code)

    if not profile_dir:
        raise ValueError(f"无法解析平台 [{platform_code}] 的 Chrome profile 目录，请在业务线配置 chrome_user_data_dir")

    # 相对路径 -> 相对项目根的绝对路径
    p = Path(profile_dir)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p)


def get_deepseek_api_key() -> str:
    """读取 DeepSeek API Key（conf/api_key.json）"""
    if not API_KEY_FILE.exists():
        raise FileNotFoundError(f"未找到 API Key 文件: {API_KEY_FILE}")
    data = json.loads(API_KEY_FILE.read_text(encoding="utf-8"))
    key = data.get("deepseek", {}).get("api_key")
    if not key:
        raise ValueError(f"{API_KEY_FILE} 中缺少 deepseek.api_key")
    return key
