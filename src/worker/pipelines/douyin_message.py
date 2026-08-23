"""
抖音私信发送 Pipeline

复用 TikTok 私信管线的核心逻辑，适配抖音的 URL 和页面选择器。
抖音私信规则：对方回复/关注前只能发 1 条文字消息。
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

# 复用 TikTok 管线的通用函数
from src.worker.pipelines.tiktok_message import (  # noqa: E402
    _load_contacts_by_ids,
    _count_messages_sent_today,
    _update_contact_status,
    _record_interaction,
    generate_personalized_message,
    _format_business_info_suffix,
    _update_counters,
)


async def send_dm_via_browser_douyin(page, contact: dict, message_text: str, ctx) -> bool:
    """
    通过浏览器自动化发送抖音私信。

    抖音私信流程：
    1. 导航到目标用户主页
    2. 点击"发私信"按钮
    3. 输入消息内容
    4. 点击发送
    """
    username = contact.get("username") or contact.get("platform_user_id", "")
    profile_url = contact.get("profile_url") or f"https://www.douyin.com/user/{username}"

    try:
        # 1. 导航到用户主页
        ctx.log("info", f"导航到用户主页: {profile_url}")
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 2. 查找并点击"发私信"按钮
        message_btn_selectors = [
            '[data-e2e="user-info-message"]',
            'button:has-text("发私信")',
            'button:has-text("私信")',
            '[class*="message-btn"]',
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
            '[data-e2e="chat-input"]',
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
            '[data-e2e="chat-send"]',
            'button:has-text("发送")',
            'button:has-text("Send")',
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
            try:
                await page.keyboard.press("Enter")
                send_found = True
                ctx.log("info", "通过 Enter 键发送消息")
            except Exception:
                ctx.log("warn", "未找到发送按钮且 Enter 发送失败")
                return False

        await asyncio.sleep(2)

        # 5. 检测发送结果
        error_indicators = [
            'text="对方未关注你"',
            'text="发送失败"',
            'text="操作过于频繁"',
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


async def run_message(task: dict, ctx):
    """执行抖音私信发送任务"""
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

    contacts = _load_contacts_by_ids(target_ids)
    if not contacts:
        raise ValueError(f"未找到有效联系人（共请求 {len(target_ids)} 个）")

    ctx.log("info", f"已加载 {len(contacts)} 个目标联系人")

    deepseek_key = ""
    if message_mode == "personalized":
        try:
            deepseek_key = config.get_deepseek_api_key()
            ctx.log("info", "✅ 已加载 DeepSeek API Key")
        except Exception as e:
            ctx.log("warn", f"DeepSeek API Key 加载失败，降级为模板消息: {e}")
            message_mode = "fallback"

    # 风控检查
    daily_limit = int(config.get_risk_config("message_daily_limit", "100"))
    sent_today = _count_messages_sent_today(task.get("account_id"))
    if sent_today >= daily_limit:
        raise ValueError(f"今日已发送 {sent_today} 条，达到上限 {daily_limit}")
    ctx.log("info", f"风控检查：今日已发送 {sent_today}/{daily_limit} 条")

    # 打开浏览器
    account_id = task.get("account_id")
    account_config = config.load_account_config(account_id) if account_id else None

    profile_dir = config.resolve_chrome_profile(task.get("bl_config"), task.get("platform_code"))
    headless = config.is_headless()

    use_adspower = False
    adspower_user_id = None

    if account_config and account_config.get("browser_id"):
        use_adspower = True
        adspower_user_id = account_config["browser_id"]
        ctx.log("info", f"✅ 已加载账号配置: {account_config['account_name']}")
    else:
        ctx.log("info", f"任务启动，打开浏览器（profile={profile_dir}）")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        if use_adspower:
            api_key = os.environ.get("ADSPOWER_API_KEY", "").strip()
            api_base_url = os.environ.get("ADSPOWER_API_BASE_URL", "http://127.0.0.1:50325")
            kwargs = {"base_url": api_base_url}
            if api_key:
                kwargs["api_key"] = api_key

            ws_endpoint = get_adspower_ws(adspower_user_id, **kwargs)
            if not ws_endpoint:
                ctx.log("warn", "AdsPower 连接失败，降级为本地浏览器")
                context = await p.chromium.launch_persistent_context(
                    profile_dir, headless=headless, no_viewport=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = context.pages[0] if context.pages else await context.new_page()
                use_adspower = False
            else:
                browser = await p.chromium.connect_over_cdp(ws_endpoint)
                if not browser.contexts:
                    context = await p.chromium.launch_persistent_context(
                        profile_dir, headless=headless, no_viewport=True,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    page = context.pages[0] if context.pages else await context.new_page()
                    use_adspower = False
                else:
                    context = browser.contexts[0]
                    page = context.pages[0] if context.pages else await context.new_page()
        else:
            context = await p.chromium.launch_persistent_context(
                profile_dir, headless=headless, no_viewport=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()

        try:
            # 检查抖音登录状态
            ctx.log("info", "检查抖音登录状态...")
            await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

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

                # 生成消息
                if message_mode == "personalized":
                    message_text = await generate_personalized_message(contact, deepseek_key, business_info_suffix)
                elif message_mode == "fixed" and fixed_message:
                    message_text = fixed_message
                else:
                    metadata = json.loads(contact.get("metadata") or "{}")
                    kw = metadata.get("source_keyword", "")
                    message_text = f"你好！看到你对{kw}相关内容很感兴趣，有兴趣聊聊吗？"

                # 附带商家信息（固定话术/fallback 模式在末尾追加）
                if business_info_suffix and message_mode != "personalized":
                    message_text = f"{message_text}\n{business_info_suffix}"

                if not message_text:
                    failed_count += 1
                    _update_counters(ctx, total, success_count, failed_count)
                    continue

                # 发送
                success = await send_dm_via_browser_douyin(page, contact, message_text, ctx)

                if success:
                    success_count += 1
                    _update_contact_status(contact["id"], "contacted")
                    _record_interaction(contact["id"], task_id, json.dumps({
                        "message": message_text[:100], "mode": message_mode,
                    }, ensure_ascii=False))
                    ctx.log("info", f"✅ 已发送私信给 {username}")
                else:
                    failed_count += 1
                    ctx.log("warn", f"⚠️ 发送失败: {username}")

                _update_counters(ctx, total, success_count, failed_count)

                # 风控间隔
                if idx < total - 1:
                    interval_min = int(config.get_risk_config("message_send_interval_min", "5"))
                    interval_max = int(config.get_risk_config("message_send_interval_max", "15"))
                    wait_seconds = random.randint(interval_min * 60, interval_max * 60)
                    ctx.log("info", f"风控等待 {wait_seconds} 秒...")
                    for _ in range(wait_seconds // 5):
                        if ctx.is_cancelled():
                            break
                        await asyncio.sleep(5)

            ctx.log("info", f"发送完成：成功 {success_count} 条，失败 {failed_count} 条")
            ctx.update_progress(progress=100, pending=0)

        finally:
            try:
                if not use_adspower:
                    await context.close()
                else:
                    ctx.log("info", "AdsPower 档案保持运行")
            except Exception:
                pass
