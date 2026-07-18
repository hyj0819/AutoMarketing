"""
任务执行 Worker 启动脚本

以独立进程运行，轮询 SQLite 中 task_executions.status='queued' 的任务并串行执行。
用法：
    python worker.py
"""

from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    from src.worker.runner import main

    main()
