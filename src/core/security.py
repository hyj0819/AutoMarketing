"""
安全模块 - API Key 加密解密
"""

import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# Fernet 要求 URL-safe base64 编码的 32 字节密钥
# 这是一个固定的默认密钥，生产环境请通过 AES_ENCRYPTION_KEY 环境变量覆盖
DEFAULT_FERNET_KEY = 'y3jTvlxrf55j2AmZYlqP_SxBH81mjpMS822hXF7qaBU='

AES_KEY = os.getenv('AES_ENCRYPTION_KEY', DEFAULT_FERNET_KEY)

try:
    fernet = Fernet(AES_KEY)
except Exception as e:
    raise ValueError(
        f"AES_ENCRYPTION_KEY 配置无效: {AES_KEY!r}。"
        f"Fernet 密钥必须是 32 字节 URL-safe base64 编码字符串。"
        f"请通过 Fernet.generate_key() 生成合法密钥。"
    ) from e


def encrypt_api_key(api_key: str) -> str:
    """加密 API Key"""
    if not api_key:
        return ''
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """解密 API Key，解密失败返回空字符串"""
    if not encrypted_key:
        return ''
    try:
        return fernet.decrypt(encrypted_key.encode()).decode()
    except Exception:
        return ''


def mask_api_key(api_key: str) -> str:
    """脱敏显示 API Key"""
    if not api_key or len(api_key) <= 8:
        return '******'
    prefix = api_key[:4]
    suffix = api_key[-4:]
    return f"{prefix}******{suffix}"


# ==================== JWT 签名密钥与门户令牌 ====================
# 门户（客户控制台）与自用端共用一把签名密钥，但令牌里带 kind 区分：
# kind='portal' 的令牌只能访问 /api/portal/*，内部令牌也不能用来登录门户。

APP_ENV = os.getenv('APP_ENV', 'development').lower()
DEV_FALLBACK_SECRET = 'automarketing-dev-secret-not-for-production'
PORTAL_TOKEN_KIND = 'portal'
INTERNAL_TOKEN_KIND = 'internal'
PORTAL_TOKEN_EXPIRE_HOURS = int(os.getenv('PORTAL_TOKEN_EXPIRE_HOURS', '24'))


def get_jwt_secret() -> str:
    """获取 JWT 签名密钥

    生产环境（APP_ENV=prod|production）必须显式配置 JWT_SECRET_KEY，
    缺失直接启动失败，避免带着硬编码密钥上线。
    """
    key = os.getenv('JWT_SECRET_KEY')
    if key:
        return key
    if APP_ENV in ('prod', 'production'):
        raise RuntimeError(
            "生产环境必须通过环境变量 JWT_SECRET_KEY 配置 JWT 签名密钥，"
            "不允许使用内置回退值。"
        )
    return DEV_FALLBACK_SECRET


def create_portal_token(account_id: int, tenant_id: int, role: str, email: str) -> str:
    """签发门户令牌：payload 里带 kind / tid / role，租户只从令牌取"""
    from datetime import datetime, timedelta
    from jose import jwt

    expire = datetime.utcnow() + timedelta(hours=PORTAL_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(account_id),
        "kind": PORTAL_TOKEN_KIND,
        "tid": int(tenant_id),
        "role": role,
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_portal_token(token: str) -> dict | None:
    """解析门户令牌，失败或 kind 不是 portal 时返回 None"""
    from jose import jwt, JWTError

    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except (JWTError, ValueError, AttributeError):
        return None
    if payload.get("kind") != PORTAL_TOKEN_KIND:
        return None
    return payload


RESET_TOKEN_KIND = 'portal_reset'
RESET_TOKEN_EXPIRE_HOURS = 2


def create_reset_token(email: str) -> str:
    """签发密码重置令牌（原型没有邮件服务，令牌直接返回给前端联调用）"""
    from datetime import datetime, timedelta
    from jose import jwt

    expire = datetime.utcnow() + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
    payload = {"kind": RESET_TOKEN_KIND, "email": email, "exp": expire}
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_reset_token(token: str) -> str | None:
    """解析重置令牌，返回邮箱；失败返回 None"""
    from jose import jwt, JWTError

    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except (JWTError, ValueError, AttributeError):
        return None
    if payload.get("kind") != RESET_TOKEN_KIND:
        return None
    return payload.get("email")
