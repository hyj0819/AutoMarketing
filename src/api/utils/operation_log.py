"""
操作日志记录工具
"""

from sqlalchemy.orm import Session
from sqlalchemy import text


def log_operation(
    db: Session,
    operation_type: str,
    operator: str = "admin",
    target_type: str = None,
    target_id: int = None,
    operation_detail: str = None,
    ip_address: str = None,
):
    """
    记录操作日志

    Args:
        db: 数据库会话
        operation_type: 操作类型（如：创建账号、删除账号、编辑账号等）
        operator: 操作人
        target_type: 目标类型（如：account、platform、keyword等）
        target_id: 目标ID
        operation_detail: 操作详情
        ip_address: IP地址
    """
    try:
        query = text("""
            INSERT INTO operation_logs 
            (operation_type, operator, target_type, target_id, operation_detail, ip_address)
            VALUES (:operation_type, :operator, :target_type, :target_id, :operation_detail, :ip_address)
        """)
        db.execute(query, {
            "operation_type": operation_type,
            "operator": operator,
            "target_type": target_type,
            "target_id": target_id,
            "operation_detail": operation_detail,
            "ip_address": ip_address,
        })
        db.commit()
    except Exception as e:
        # 日志记录失败不应影响主流程，仅回滚并打印错误
        db.rollback()
        print(f"记录操作日志失败: {e}")
