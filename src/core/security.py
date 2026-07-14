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
