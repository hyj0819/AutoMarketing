"""
TikTok 私信发送 Pipeline

流程：
1. 解析 task_config → 加载目标联系人列表
2. 打开浏览器（复用 AdsPower / 本地 Chrome 逻辑）
3. 风控检查：今日已发送数量
4. 逐个发送私信：
   a. 个性化模式：AI 根据联系人元数据直接生成消息
   b. 固定话术模式：使用用户输入的固定内容
   c. 浏览器自动化：导航到用户主页 → 打开私信 → 输入消息 → 发送
   d. 更新联系人状态 + 写入 contact_interactions
   e. 风控间隔（从 system_configs 读取）
5. 完成
"""

import asyncio
import json
import os
import random
import sys

from sqlalchemy import text

from src.core.database import SessionLocal
from src.worker import config

_PROJECT_ROOT = config.PROJECT_ROOT
sys.path.append(str(_PROJECT_ROOT / "src" / "utils"))

from common_utils import get_text_response_ds, get_adspower_ws  # noqa: E402


# ==================== 数据库工具 ====================


def _load_contacts_by_ids(contact_ids: list[int]) -> list[dict]:
    """根据 ID 列表加载联系人（仅 pending 状态）"""
    if not contact_ids:
        return []
    db = SessionLocal()
    try:
        ids_str = ",".join(str(i) for i in contact_ids)
        rows = db.execute(
            text(f"""
                SELECT c.*, p.name as platform_name
                FROM contacts c
                LEFT JOIN platforms p ON c.platform_id = p.id
                WHERE c.id IN ({ids_str})
            """)
        ).fetchall()
        return [dict(row._mapping) for row in rows]
    finally:
        db.close()


def _count_messages_sent_today(account_id: int | None) -> int:
    """统计今日已发送的私信数量"""
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT COUNT(*) as cnt FROM contact_interactions ci
                JOIN task_executions te ON ci.task_execution_id = te.id
                WHERE ci.interaction_type = 'message_sent'
                  AND DATE(ci.created_at) = DATE('now')
            """)
        ).fetchone()
        return row.cnt if row else 0
    finally:
        db.close()


def _update_contact_status(contact_id: int, status: str):
    """更新联系人状态"""
    db = SessionLocal()
    try:
        db.execute(
            text("""
                UPDATE contacts
                SET contact_status = :status,
                    last_contact_at = CURRENT_TIMESTAMP,
                    contact_attempts = contact_attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"id": contact_id, "status": status},
        )
        db.commit()
    except Exception as e:
        print(f"⚠️ 更新联系人状态失败: {e}")
        db.rollback()
    finally:
        db.close()


def _record_interaction(contact_id: int, task_id: int, detail: str):
    """记录触达交互"""
    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO contact_interactions (contact_id, interaction_type, task_execution_id, detail)
                VALUES (:cid, 'message_sent', :tid, :detail)
            """),
            {"cid": contact_id, "tid": task_id, "detail": detail},
        )
        db.commit()
    except Exception as e:
        print(f"⚠️ 记录交互失败: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== AI 消息生成 ====================


def _format_business_info_suffix(business_profile: dict) -> str:
    """将商家信息字典格式化为消息末尾的附缀文本"""
    if not business_profile:
        return ""
    label_map = {
        "phone": "电话",
        "wechat": "微信",
        "shop_name": "店铺",
        "shop_address": "地址",
        "site_url": "官网",
    }
    parts = []
    for key, label in label_map.items():
        val = (business_profile.get(key) or "").strip()
        if val:
            parts.append(f"{label}: {val}")
    return " | ".join(parts)


async def generate_personalized_message(contact: dict, deepseek_key: str, business_info_suffix: str = "") -> str:
    """AI 直接从联系人元数据生成个性化私信消息"""
    metadata = json.loads(contact.get("metadata") or "{}")

    system_prompt = (
        "你是一个专业的社交媒体运营专家。根据以下信息，生成一条自然的私信消息。\n"
        "要求：\n"
        "1. 语气自然友好，像朋友聊天\n"
        "2. 简洁，不超过 200 字\n"
        "3. 不要使用表情符号\n"
        "4. 直接输出消息内容，不要任何解释或前缀\n"
        "5. 不要提及你是 AI 或机器人"
    )
    if business_info_suffix:
        system_prompt += (
            "\n6. 在消息末尾自然地附上以下商家联系方式，不要太生硬：" + business_info_suffix
        )
    user_prompt = (
        f"平台: {contact.get('platform_name', 'TikTok')}\n"
        f"目标用户: {contact.get('username', contact.get('platform_user_id', ''))}\n"
        f"搜索关键词: {metadata.get('source_keyword', '')}\n"
        f"视频标题: {metadata.get('source_title', '')}\n"
        f"用户评论: {metadata.get('comment', '')}\n"
        f"\n请根据以上信息生成一条私信消息。"
    )

    try:
        result = await asyncio.to_thread(
            get_text_response_ds,
            system_prompt,
            user_prompt,
            "deepseek-chat",
            deepseek_key,
        )
        return (result or "").strip()[:200]
    except Exception:
        # AI 失败降级：生成简单模板消息
        kw = metadata.get("source_keyword", "")
        username = contact.get("username", "")
        return f"你好{' ' + username if username else ''}！看到你对{kw}相关内容很感兴趣，我们刚好做这个，有兴趣聊聊吗？"


# ==================== 浏览器自动化 ====================


async def send_dm_via_browser(page, contact: dict, message_text: str, ctx) -> bool:
    """
    通过浏览器自动化发送 TikTok 私信。

    流程：
    1. 导航到目标用户主页
    2. 点击 Message 按钮
    3. 输入消息内容
    4. 点击发送
    5. 等待发送确认

    返回 True/False 表示是否成功。
    """
    username = contact.get("username") or contact.get("platform_user_id", "")
    profile_url = contact.get("profile_url") or f"https://www.tiktok.com/@{username}"

    try:
        # 1. 导航到用户主页
        ctx.log("info", f"导航到用户主页: {profile_url}")
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 2. 查找并点击 Message 按钮
        # TikTok 的私信按钮选择器（可能需要根据实际页面调整）
        message_btn_selectors = [
            '[data-e2e="message-button"]',
            'button:has-text("Message")',
            'button:has-text("消息")',
            '[data-testid="message-button"]',
        ]

        btn_found = False
        for selector in message_btn_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=3000):
                    await btn.click()
                    btn_found = True
                    ctx.log("info", f"已点击私信按钮 (selector: {selector})")
                    break
            except Exception:
                continue

        if not btn_found:
            ctx.log("warn", f"未找到私信按钮，用户 {username} 可能不支持私信")
            return False

        await asyncio.sleep(2)

        # 3. 在消息输入框中输入内容
        input_selectors = [
            '[data-e2e="message-input"]',
            '[contenteditable="true"]',
            'div[role="textbox"]',
            'textarea',
        ]

        input_found = False
        for selector in input_selectors:
            try:
                input_el = page.locator(selector).first
                if await input_el.is_visible(timeout=3000):
                    await input_el.click()
                    await input_el.fill(message_text)
                    input_found = True
                    ctx.log("info", "已输入消息内容")
                    break
            except Exception:
                continue

        if not input_found:
            ctx.log("warn", "未找到消息输入框")
            return False

        await asyncio.sleep(1)

        # 4. 点击发送按钮
        send_btn_selectors = [
            '[data-e2e="message-send"]',
            'button:has-text("Send")',
            'button:has-text("发送")',
            '[data-testid="send-button"]',
        ]

        send_found = False
        for selector in send_btn_selectors:
            try:
                send_btn = page.locator(selector).first
                if await send_btn.is_visible(timeout=3000):
                    await send_btn.click()
                    send_found = True
                    ctx.log("info", "已点击发送按钮")
                    break
            except Exception:
                continue

        if not send_found:
            # 尝试按 Enter 发送
            try:
                await page.keyboard.press("Enter")
                send_found = True
                ctx.log("info", "通过 Enter 键发送消息")
            except Exception:
                ctx.log("warn", "未找到发送按钮且 Enter 发送失败")
                return False

        await asyncio.sleep(2)

        # 5. 检测发送结果
        # 检查是否有错误提示（如频率限制等）
        error_indicators = [
            'text="发送过于频繁"',
            'text="rate limit"',
            'text="暂时无法发送"',
        ]
        for indicator in error_indicators:
            try:
                if await page.locator(indicator).first.is_visible(timeout=1000):
                    ctx.log("warn", f"检测到发送限制: {indicator}")
                    return False
            except Exception:
                continue

        return True

    except Exception as e:
        ctx.log("error", f"发送私信异常: {e}")
        return False


# ==================== 主流程 ====================


async def run_message(task: dict, ctx):
    """执行 TikTok 私信发送任务"""
    task_id = task["id"]
    cfg = json.loads(task.get("task_config") or "{}")
    target_ids = cfg.get("target_contact_ids", [])
    message_mode = cfg.get("message_mode", "personalized")
    fixed_message = cfg.get("fixed_message", "")

    # 商家信息附带
    include_biz = cfg.get("include_business_info", False)
    biz_profile = cfg.get("business_profile", {})
    business_info_suffix = _format_business_info_suffix(biz_profile) if include_biz else ""

    if not target_ids:
        raise ValueError("任务配置缺少目标联系人")

    # 1. 加载联系人
    contacts = _load_contacts_by_ids(target_ids)
    if not contacts:
        raise ValueError(f"未找到有效联系人（共请求 {len(target_ids)} 个）")

    ctx.log("info", f"已加载 {len(contacts)} 个目标联系人")

    # 2. 个性化模式：加载 DeepSeek API Key
    deepseek_key = ""
    if message_mode == "personalized":
        try:
            deepseek_key = config.get_deepseek_api_key()
            ctx.log("info", "✅ 已加载 DeepSeek API Key，将使用 AI 生成个性化消息")
        except Exception as e:
            ctx.log("warn", f"DeepSeek API Key 加载失败，降级为模板消息: {e}")
            message_mode = "fallback"

    # 3. 风控检查
    daily_limit = int(config.get_risk_config("message_daily_limit", "100"))
    sent_today = _count_messages_sent_today(task.get("account_id"))
    if sent_today >= daily_limit:
        raise ValueError(f"今日已发送 {sent_today} 条，达到上限 {daily_limit}，请明天再试")
    ctx.log("info", f"风控检查：今日已发送 {sent_today}/{daily_limit} 条")

    # 4. 打开浏览器
    account_id = task.get("account_id")
    account_config = None
    if account_id:
        account_config = config.load_account_config(account_id)

    profile_dir = config.resolve_chrome_profile(task.get("bl_config"), task.get("platform_code"))
    headless = config.is_headless()

    use_adspower = False
    adspower_user_id = None
    account_name = None

    if account_config and account_config.get("browser_id"):
        use_adspower = True
        adspower_user_id = account_config["browser_id"]
        account_name = account_config["account_name"]
        ctx.log("info", f"✅ 已加载账号配置: {account_name}")
    else:
        ctx.log("info", f"任务启动，打开浏览器（profile={profile_dir}, headless={headless}）")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        if use_adspower:
            api_key = os.environ.get("ADSPOWER_API_KEY", "").strip()
            api_base_url = os.environ.get("ADSPOWER_API_BASE_URL", "http://127.0.0.1:50325")
            kwargs = {"base_url": api_base_url}
            if api_key:
                kwargs["api_key"] = api_key

            ctx.log("info", f"尝试连接 AdsPower（user_id={adspower_user_id}）")
            ws_endpoint = get_adspower_ws(adspower_user_id, **kwargs)

            if not ws_endpoint:
                ctx.log("warn", "AdsPower 连接失败，降级为本地浏览器")
                context = await p.chromium.launch_persistent_context(
                    profile_dir,
                    headless=headless,
                    no_viewport=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = context.pages[0] if context.pages else await context.new_page()
                use_adspower = False
            else:
                browser = await p.chromium.connect_over_cdp(ws_endpoint)
                if not browser.contexts:
                    ctx.log("warn", "AdsPower 未返回浏览器上下文，降级")
                    context = await p.chromium.launch_persistent_context(
                        profile_dir,
                        headless=headless,
                        no_viewport=True,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    page = context.pages[0] if context.pages else await context.new_page()
                    use_adspower = False
                else:
                    context = browser.contexts[0]
                    page = context.pages[0] if context.pages else await context.new_page()
                    ctx.log("info", f"✅ 已连接 AdsPower 档案: {adspower_user_id}")
        else:
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=headless,
                no_viewport=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()

        try:
            # 5. 确保已登录 TikTok
            ctx.log("info", "检查 TikTok 登录状态...")
            await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # 简单检测登录状态（检查是否有登录按钮）
            try:
                login_btn = page.locator('[data-e2e="navbar-login-button"]').first
                if await login_btn.is_visible(timeout=3000):
                    ctx.log("warn", "⚠️ 检测到未登录状态，请先浏览器中手动登录 TikTok")
                    # 等待用户手动登录（最多等 120 秒）
                    ctx.log("info", "等待手动登录（最多 120 秒）...")
                    for _ in range(24):
                        await asyncio.sleep(5)
                        try:
                            if not await page.locator('[data-e2e="navbar-login-button"]').first.is_visible(timeout=1000):
                                ctx.log("info", "✅ 检测到已登录")
                                break
                        except Exception:
                            ctx.log("info", "✅ 检测到已登录")
                            break
                    else:
                        raise ValueError("登录超时，请在浏览器中手动登录后重试")
            except Exception:
                ctx.log("info", "✅ 已处于登录状态")

            # 6. 逐个发送私信
            total = len(contacts)
            success_count = 0
            failed_count = 0
            ctx.update_progress(total=total, success=0, failed=0, pending=total, progress=0)

            for idx, contact in enumerate(contacts):
                if ctx.is_cancelled():
                    ctx.log("warn", "检测到停止信号，中断发送")
                    break

                username = contact.get("username") or contact.get("platform_user_id", "")
                ctx.log("info", f"[{idx + 1}/{total}] 准备发送私信给: {username}")

                # 6a. 生成消息内容
                if message_mode == "personalized":
                    message_text = await generate_personalized_message(contact, deepseek_key, business_info_suffix)
                elif message_mode == "fixed" and fixed_message:
                    message_text = fixed_message
                else:
                    # fallback 模式
                    metadata = json.loads(contact.get("metadata") or "{}")
                    kw = metadata.get("source_keyword", "")
                    message_text = f"你好！看到你对{kw}相关内容很感兴趣，我们刚好做这个，有兴趣聊聊吗？"

                # 附带商家信息（固定话术/fallback 模式在末尾追加）
                if business_info_suffix and message_mode != "personalized":
                    message_text = f"{message_text}\n{business_info_suffix}"

                if not message_text:
                    ctx.log("warn", f"消息内容为空，跳过 {username}")
                    failed_count += 1
                    _update_counters(ctx, total, success_count, failed_count)
                    continue

                # 6b. 浏览器自动化发送
                success = await send_dm_via_browser(page, contact, message_text, ctx)

                # 6c. 更新状态
                if success:
                    success_count += 1
                    _update_contact_status(contact["id"], "contacted")
                    _record_interaction(contact["id"], task_id, json.dumps({
                        "message": message_text[:100],
                        "mode": message_mode,
                    }, ensure_ascii=False))
                    ctx.log("info", f"✅ 已发送私信给 {username}")
                else:
                    failed_count += 1
                    ctx.log("warn", f"⚠️ 发送失败: {username}")

                _update_counters(ctx, total, success_count, failed_count)

                # 6d. 风控间隔
                if idx < total - 1:  # 最后一个不需要等待
                    interval_min = int(config.get_risk_config("message_send_interval_min", "5"))
                    interval_max = int(config.get_risk_config("message_send_interval_max", "15"))
                    wait_seconds = random.randint(interval_min * 60, interval_max * 60)
                    ctx.log("info", f"风控等待 {wait_seconds} 秒...")
                    # 分段等待，便于检测取消信号
                    for _ in range(wait_seconds // 5):
                        if ctx.is_cancelled():
                            break
                        await asyncio.sleep(5)

            ctx.log(
                "info",
                f"发送完成：成功 {success_count} 条，失败 {failed_count} 条，共 {total} 条",
            )
            ctx.update_progress(progress=100, pending=0)

        finally:
            try:
                if not use_adspower:
                    await context.close()
                else:
                    ctx.log("info", "AdsPower 档案保持运行，供后续任务复用。")
            except Exception:
                pass


def _update_counters(ctx, total: int, success: int, failed: int):
    """统一回写 success/failed/pending/progress"""
    done = success + failed
    pending = max(total - done, 0)
    progress = int(done / total * 100) if total else 0
    ctx.update_progress(success=success, failed=failed, pending=pending, progress=progress)
