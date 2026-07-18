"""
Worker 引擎层联调测试（mock pipeline，不开浏览器）
验证：认领(queued->running) / 进度回写 / 日志 / 终态 / 停止检测 / 异常 / 不支持组合
"""
from sqlalchemy import text
from src.core.database import SessionLocal
from src.worker import runner
import src.worker.pipelines.tiktok_scrape as pl

BL_ID = 6  # tiktok / golf


def _mk_task(name, status="queued"):
    db = SessionLocal()
    db.execute(text("""
        INSERT INTO task_executions (task_name, task_type, business_line_id, status, task_config, total_items, pending_items)
        VALUES (:n, 'scrape', :bl, :st, '{"keywords":["x"]}', 0, 0)
    """), {"n": name, "bl": BL_ID, "st": status})
    tid = db.execute(text("SELECT last_insert_rowid() as id")).fetchone()[0]
    db.commit(); db.close()
    return tid


def _get(tid):
    db = SessionLocal()
    r = db.execute(text("SELECT status,progress,success_items,failed_items,pending_items,total_items,start_time,end_time,error_message FROM task_executions WHERE id=:i"), {"i": tid}).fetchone()
    db.close()
    return r


def _logs(tid):
    db = SessionLocal()
    rs = db.execute(text("SELECT log_level,message FROM task_logs WHERE task_id=:i ORDER BY id"), {"i": tid}).fetchall()
    db.close()
    return [(x.log_level, x.message) for x in rs]


def _cleanup(tids):
    db = SessionLocal()
    for t in tids:
        db.execute(text("DELETE FROM task_logs WHERE task_id=:i"), {"i": t})
        db.execute(text("DELETE FROM task_executions WHERE id=:i"), {"i": t})
    db.commit(); db.close()


created = []
try:
    # ---------- 场景1: 正常成功 + 进度回写 ----------
    async def mock_ok(task, ctx):
        ctx.log("info", "mock 开始")
        ctx.update_progress(total=10, success=0, failed=0, pending=10, progress=0)
        for i in range(1, 11):
            if ctx.is_cancelled():
                ctx.log("warn", "检测到停止")
                return
            ctx.update_progress(success=i, pending=10 - i, progress=i * 10)
        ctx.log("info", "mock 完成")
    pl.run_scrape = mock_ok

    t1 = _mk_task("引擎测试-成功"); created.append(t1)
    claimed = runner._claim_next_task()
    assert claimed and claimed["id"] == t1, f"认领失败: {claimed}"
    r = _get(t1)
    assert r.status == "running" and r.start_time, f"认领后应 running+start_time: {r}"
    print(f"[场景1] 认领 OK: status={r.status}, start_time set")
    runner._process_task(claimed)
    r = _get(t1)
    assert r.status == "success" and r.progress == 100 and r.success_items == 10 and r.end_time, f"终态异常: {r}"
    print(f"[场景1] 成功终态 OK: status={r.status}, progress={r.progress}, success={r.success_items}, end_time set")
    print(f"[场景1] 日志: {_logs(t1)}")

    # ---------- 场景2: 停止检测 (running->cancelled 后中断) ----------
    async def mock_cancel(task, ctx):
        ctx.log("info", "mock 开始(将被停止)")
        ctx.update_progress(total=5, progress=0)
        db = SessionLocal()
        db.execute(text("UPDATE task_executions SET status='cancelled' WHERE id=:i"), {"i": task["id"]})
        db.commit(); db.close()
        for i in range(5):
            if ctx.is_cancelled():
                ctx.log("warn", "检测到停止，中断")
                return
            ctx.update_progress(success=i + 1)
    pl.run_scrape = mock_cancel

    t2 = _mk_task("引擎测试-停止"); created.append(t2)
    claimed = runner._claim_next_task()
    assert claimed["id"] == t2
    runner._process_task(claimed)
    r = _get(t2)
    assert r.status == "cancelled", f"应保持 cancelled, 不被覆盖成 success: {r}"
    print(f"[场景2] 停止检测 OK: status={r.status}（未被覆盖为 success）")
    print(f"[场景2] 日志: {_logs(t2)}")

    # ---------- 场景3: 异常 -> failed + error_message ----------
    async def mock_err(task, ctx):
        ctx.log("info", "mock 开始(将抛异常)")
        raise RuntimeError("模拟爬取异常")
    pl.run_scrape = mock_err

    t3 = _mk_task("引擎测试-异常"); created.append(t3)
    claimed = runner._claim_next_task()
    assert claimed["id"] == t3
    runner._process_task(claimed)
    r = _get(t3)
    assert r.status == "failed" and r.error_message and "模拟爬取异常" in r.error_message, f"应 failed+error: {r}"
    print(f"[场景3] 异常终态 OK: status={r.status}, error_message='{r.error_message}'")

    # ---------- 场景4: 不支持组合 -> failed ----------
    t4 = _mk_task("引擎测试-不支持"); created.append(t4)
    db = SessionLocal()
    db.execute(text("UPDATE task_executions SET task_type='unknown_type' WHERE id=:i"), {"i": t4})
    db.commit(); db.close()
    claimed = runner._claim_next_task()
    assert claimed["id"] == t4
    runner._process_task(claimed)
    r = _get(t4)
    assert r.status == "failed" and "不支持" in (r.error_message or ""), f"应 failed(不支持): {r}"
    print(f"[场景4] 不支持组合 OK: status={r.status}, error_message='{r.error_message}'")

    # ---------- 场景5: 空队列返回 None ----------
    nxt = runner._claim_next_task()
    assert nxt is None, f"空队列应返回 None, 实际: {nxt}"
    print(f"[场景5] 空队列 OK: 无 queued 任务时返回 None")

    print("\n全部引擎层场景通过")
finally:
    _cleanup(created)
    print(f"已清理临时任务: {created}")
