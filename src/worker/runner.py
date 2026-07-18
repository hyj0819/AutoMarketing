"""
Worker 主循环 / 状态机 / 数据库工具方法

以 SQLite 的 task_executions.status 作为任务队列：
    pending -> queued(点击启动) -> running(worker认领) -> success/failed/cancelled

设计要点：
- 串行执行（并发=1），保护账号，避免多浏览器同时操作被风控。
- 每次数据库更新后立即 commit，保证前端轮询能实时看到进度。
- 步骤间通过 is_cancelled() 检测停止信号，命中则中断并清理。
"""

import asyncio
import signal
import time
import traceback

from sqlalchemy import text

from src.core.database import SessionLocal
from src.worker import config

# 优雅退出标记
_should_exit = False


def _install_signal_handlers():
    """捕获 SIGINT/SIGTERM，等当前任务步骤结束后退出"""

    def _handler(signum, frame):
        global _should_exit
        print(f"\n⚠️ 收到信号 {signum}，将在当前任务空档退出...")
        _should_exit = True

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# ==================== 数据库工具方法 ====================


class TaskContext:
    """
    传递给 pipeline 的执行上下文，封装日志、进度、取消检测等数据库操作。
    每个方法内部使用独立 session 并 commit，避免长事务占用连接。
    """

    def __init__(self, task_id: int):
        self.task_id = task_id

    def log(self, level: str, message: str):
        """写入一条任务日志（level: info/warn/error）"""
        print(f"[task {self.task_id}][{level}] {message}")
        db = SessionLocal()
        try:
            db.execute(
                text(
                    "INSERT INTO task_logs (task_id, log_level, message) VALUES (:tid, :lv, :msg)"
                ),
                {"tid": self.task_id, "lv": level, "msg": message},
            )
            db.commit()
        except Exception as e:
            print(f"⚠️ 写日志失败: {e}")
            db.rollback()
        finally:
            db.close()

    def update_progress(
        self,
        total: int | None = None,
        success: int | None = None,
        failed: int | None = None,
        pending: int | None = None,
        progress: int | None = None,
    ):
        """更新任务进度字段（仅更新传入的非 None 字段）"""
        sets = []
        params: dict = {"tid": self.task_id}
        if total is not None:
            sets.append("total_items = :total")
            params["total"] = total
        if success is not None:
            sets.append("success_items = :success")
            params["success"] = success
        if failed is not None:
            sets.append("failed_items = :failed")
            params["failed"] = failed
        if pending is not None:
            sets.append("pending_items = :pending")
            params["pending"] = pending
        if progress is not None:
            sets.append("progress = :progress")
            params["progress"] = progress
        if not sets:
            return
        sets.append("updated_at = CURRENT_TIMESTAMP")
        db = SessionLocal()
        try:
            db.execute(
                text(f"UPDATE task_executions SET {', '.join(sets)} WHERE id = :tid"),
                params,
            )
            db.commit()
        except Exception as e:
            print(f"⚠️ 更新进度失败: {e}")
            db.rollback()
        finally:
            db.close()

    def is_cancelled(self) -> bool:
        """检测任务是否被外部置为 cancelled（用于步骤间中断）"""
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT status FROM task_executions WHERE id = :tid"),
                {"tid": self.task_id},
            ).fetchone()
            return bool(row) and row.status == "cancelled"
        except Exception:
            return False
        finally:
            db.close()


def _claim_next_task():
    """
    取出并认领下一个 queued 任务（按创建时间升序）。
    返回认领成功的任务行（dict），无任务返回 None。
    """
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT t.*, bl.code as bl_code, bl.config as bl_config,
                       p.code as platform_code
                FROM task_executions t
                LEFT JOIN business_lines bl ON t.business_line_id = bl.id
                LEFT JOIN platforms p ON bl.platform_id = p.id
                WHERE t.status = 'queued'
                ORDER BY t.created_at ASC
                LIMIT 1
                """
            )
        ).fetchone()
        if not row:
            return None

        # 认领：queued -> running（乐观锁，防止重复认领）
        result = db.execute(
            text(
                """
                UPDATE task_executions
                SET status = 'running', start_time = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = :tid AND status = 'queued'
                """
            ),
            {"tid": row.id},
        )
        db.commit()
        if result.rowcount == 0:
            # 被其他进程抢先，跳过
            return None
        return dict(row._mapping)
    except Exception as e:
        print(f"⚠️ 认领任务失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def _finish_task(task_id: int, status: str, error_message: str | None = None, progress: int | None = None):
    """标记任务终态：success/failed/cancelled"""
    db = SessionLocal()
    try:
        sets = ["status = :status", "end_time = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]
        params: dict = {"tid": task_id, "status": status}
        if error_message is not None:
            sets.append("error_message = :err")
            params["err"] = error_message[:1000]
        if progress is not None:
            sets.append("progress = :progress")
            params["progress"] = progress
        db.execute(
            text(f"UPDATE task_executions SET {', '.join(sets)} WHERE id = :tid"),
            params,
        )
        db.commit()
    except Exception as e:
        print(f"⚠️ 标记任务终态失败: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== 任务分发 ====================


async def _dispatch(task: dict, ctx: TaskContext):
    """按 task_type + platform_code 分发到对应 pipeline"""
    task_type = task.get("task_type")
    platform_code = task.get("platform_code")

    if task_type == "scrape" and platform_code == "tiktok":
        from src.worker.pipelines.tiktok_scrape import run_scrape

        await run_scrape(task, ctx)
    else:
        raise NotImplementedError(
            f"暂不支持的任务组合: task_type={task_type}, platform={platform_code}"
        )


def _process_task(task: dict):
    """处理单个已认领任务：分发执行 + 终态处理"""
    task_id = task["id"]
    ctx = TaskContext(task_id)
    ctx.log("info", f"Worker 已认领任务 #{task_id}（{task.get('task_type')} / {task.get('platform_code')}）")

    try:
        asyncio.run(_dispatch(task, ctx))
    except NotImplementedError as e:
        ctx.log("error", str(e))
        _finish_task(task_id, "failed", error_message=str(e))
        return
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        ctx.log("error", f"任务执行异常: {e}")
        _finish_task(task_id, "failed", error_message=str(e))
        return

    # pipeline 内部若已置 cancelled，则不再覆盖为 success
    if ctx.is_cancelled():
        ctx.log("warn", "任务已被停止")
        return

    ctx.log("info", "任务执行完成")
    _finish_task(task_id, "success", progress=100)


# ==================== 主循环 ====================


def main():
    """Worker 主入口：轮询 queued 任务并串行执行"""
    _install_signal_handlers()
    interval = config.get_poll_interval()
    print("=" * 60)
    print("🚀 AutoMarketing 任务执行 Worker 已启动")
    print(f"   轮询间隔: {interval}s | 无头模式: {config.is_headless()}")
    print("   状态机: pending -> queued -> running -> success/failed/cancelled")
    print("=" * 60)

    while not _should_exit:
        try:
            task = _claim_next_task()
            if task:
                print(f"\n📥 认领任务 #{task['id']}: {task.get('task_name')}")
                _process_task(task)
            else:
                time.sleep(interval)
        except Exception as e:
            print(f"⚠️ 主循环异常: {e}")
            traceback.print_exc()
            time.sleep(interval)

    print("👋 Worker 已退出")
