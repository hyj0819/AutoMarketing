import asyncio
from playwright.async_api import async_playwright
import json, random

VIDEO_URL = "https://www.tiktok.com/@stastclkstocks/video/7641767208036896013"
MAX_SCROLLS = 10
MAX_RETRIES = 2          # 检测到空评论区时的最大重试次数
REFRESH_EVERY = 10       # 每爬取 N 个视频后去首页刷一刷，重置会话状态
DEFAULT_TIMEOUT = 60000  # 默认超时时间(毫秒)


async def _mimic_tiktok_feed(context):
    """去 TikTok 首页随机浏览，重置会话状态，防止评论区被限流"""
    page = await context.new_page()
    try:
        print("📺 [拟人浏览] 前往 TikTok 首页刷新会话状态...")
        await page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(3, 6))
        for _ in range(random.randint(3, 6)):
            await page.mouse.wheel(0, random.randint(500, 1000))
            await asyncio.sleep(random.uniform(2, 4))
            if random.random() < 0.2:
                await page.mouse.move(random.randint(200, 500), random.randint(200, 500))
        print("✅ [拟人浏览] 结束")
    except Exception as e:
        print(f"⚠️ [拟人浏览] 异常: {e}")
    finally:
        await page.close()


async def _is_comment_section_empty(page) -> bool:
    """
    检测评论区是否处于 "Start the conversation" 空状态。
    TikTok 限流或会话降级时会出现这个占位文案，但视频实际有评论。
    """
    empty_indicators = [
        'p[data-e2e="comment-empty-text"]',
        'div[class*="DivEmptyContainer"]',
        'span:has-text("Start the conversation")',
        'span:has-text("Be the first to comment")',
        'div[class*="empty"]',
        'div[class*="Empty"]',
        'span[data-e2e="comment-empty"]',
    ]
    for sel in empty_indicators:
        try:
            if await page.locator(sel).count() > 0:
                print(f"⚠️ 检测到评论区空状态占位符: {sel}")
                return True
        except Exception:
            pass

    # 兜底：等 3s 后仍然没有任何评论项，视为空
    comment_selectors = [
        'div.eb3imn610',
        'div[class*="DivCommentObjectWrapper"]',
        'div[class*="DivCommentItemWrapper"]',
        'div[data-e2e="comment-item"]',
        'div[class*="comment-item"]',
    ]
    for sel in comment_selectors:
        try:
            await page.wait_for_selector(sel, timeout=3000)
            return False
        except Exception:
            continue
    
    return True


async def _find_comment_button(page, timeout_ms):
    """
    尝试多种定位策略找到评论按钮。
    返回 (成功, 定位器) 元组。
    """
    selectors = [
        page.locator('button[data-testid="tux-web-icon-button"]'),
        page.locator('button[class*="tux-button__element"]'),
        page.locator('button[class*="tux-icon-button"]'),
        page.locator('button').filter(has=page.locator('span[data-e2e="comment-icon"]')),
        page.locator('button[data-e2e="comment"]'),
        page.locator('span[data-e2e="comment-icon"]').first.locator('..'),
        page.locator('[data-e2e="comment"]'),
        page.locator('button').filter(has_text="Comment"),
        page.locator('button').filter(has_text="评论"),
        page.locator('svg[viewBox="0 0 48 48"]').filter(has=page.locator('path[d*="M2 21.5"]')).first.locator('button'),
        page.locator('svg[viewBox="0 0 48 48"]').filter(has=page.locator('path[d*="M5 24a4"]')).first.locator('button'),
    ]
    
    for i, selector in enumerate(selectors):
        try:
            count = await selector.count()
            if count > 0:
                print(f"✅ 找到评论按钮，策略 #{i+1}: count={count}")
                return (True, selector)
        except Exception as e:
            print(f"⚠️ 定位策略 #{i+1} 出错: {e}")
            continue
    
    # 所有策略都失败，输出页面上所有按钮的信息用于调试
    print("❌ 所有策略都失败，输出页面上所有按钮信息...")
    try:
        buttons = page.locator('button')
        count = await buttons.count()
        print(f"📊 页面上共有 {count} 个按钮")
        
        for i in range(min(count, 20)):
            button = buttons.nth(i)
            data_testid = await button.get_attribute('data-testid')
            data_e2e = await button.get_attribute('data-e2e')
            class_name = await button.get_attribute('class')
            inner_text = await button.inner_text()
            
            print(f"  按钮 #{i}:")
            print(f"    data-testid: {data_testid}")
            print(f"    data-e2e: {data_e2e}")
            print(f"    class: {class_name}")
            print(f"    innerText: '{inner_text}'")
    except Exception as e:
        print(f"⚠️ 输出按钮信息失败: {e}")
    
    return (False, None)


async def scrape_comments(context, video_url, _retry=0, max_comments=None, log_fn=None, timeout_ms=DEFAULT_TIMEOUT):
    """
    爬取单个视频评论。
    遇到空评论区时自动重试（最多 MAX_RETRIES 次），
    重试前去首页拟人浏览以重置会话状态。

    :param max_comments: 评论采集上限，达到即停止滚动（None=不限制）
    :param log_fn: 可选日志回调 log_fn(level, message)，为 None 时仅走 print。
    :param timeout_ms: 页面操作超时时间(毫秒)，默认60秒
    """

    def _log(level, msg):
        print(msg)
        if log_fn:
            try:
                log_fn(level, msg)
            except Exception:
                pass

    page = await context.new_page()
    await page.set_viewport_size({"width": 1280, "height": 800})
    _log("info", f"🚀 正在打开 (retry={_retry}): {video_url}")

    comments = []
    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(3000)

        # 尝试多种策略找到评论按钮
        found, comment_icon_btn = await _find_comment_button(page, timeout_ms)
        if not found:
            _log("error", f"❌ 无法找到评论按钮，尝试截图分析页面...")
            await page.screenshot(path=f"/tmp/tiktok_debug_{_retry}.png")
            _log("error", f"❌ 截图已保存到 /tmp/tiktok_debug_{_retry}.png")
            await page.close()
            if _retry < MAX_RETRIES:
                wait_sec = random.randint(20, 40) * (_retry + 1)
                _log("warn", f"🔄 重试 ({_retry+1}/{MAX_RETRIES})...")
                await _mimic_tiktok_feed(context)
                await asyncio.sleep(wait_sec)
                return await scrape_comments(context, video_url, _retry=_retry + 1, max_comments=max_comments, log_fn=log_fn, timeout_ms=timeout_ms)
            else:
                _log("warn", f"❌ 重试 {MAX_RETRIES} 次后仍无法找到评论按钮，跳过该视频。")
                return comments
        
        await comment_icon_btn.first.click(timeout=timeout_ms)
        await page.wait_for_timeout(2000)

        # 点击后检查页面状态，输出调试信息
        await page.screenshot(path=f"/tmp/tiktok_after_click_{_retry}.png")
        print("📸 点击评论按钮后截图已保存")
        
        # 尝试多个评论项选择器
        item_selectors = [
            'div.eb3imn610',
            'div[class*="DivCommentObjectWrapper"]',
            'div[class*="DivCommentItemWrapper"]',
            'div[data-e2e="comment-item"]',
            'div[class*="comment-item"]',
            'div[class*="CommentItem"]',
            'li[class*="comment"]',
        ]
        
        item_selector = None
        for sel in item_selectors:
            try:
                count = await page.locator(sel).count()
                print(f"🔍 选择器 '{sel}': {count} 个元素")
                if count > 0:
                    item_selector = sel
                    print(f"✅ 使用选择器: {sel}")
                    break
            except Exception as e:
                print(f"⚠️ 选择器 '{sel}' 出错: {e}")
        
        if not item_selector:
            print("❌ 所有选择器都没有找到元素，尝试检查 iframe...")
            frames = page.frames
            print(f"📊 当前页面有 {len(frames)} 个 frame")
            for i, frame in enumerate(frames):
                print(f"  Frame {i}: {frame.name or '无名称'}")
                try:
                    for sel in item_selectors:
                        count = await frame.locator(sel).count()
                        if count > 0:
                            print(f"   ✅ 在 frame {i} 中找到 {count} 个 '{sel}'")
                            item_selector = sel
                            page = frame
                            break
                except Exception:
                    pass
            
            if not item_selector:
                print("❌ 尝试所有选择器和iframe后仍未找到评论元素")
                await page.screenshot(path=f"/tmp/tiktok_no_comments_{_retry}.png")
                _log("error", f"❌ 无法找到评论元素，截图已保存到 /tmp/tiktok_no_comments_{_retry}.png")
                await page.close()
                if _retry < MAX_RETRIES:
                    wait_sec = random.randint(20, 40) * (_retry + 1)
                    _log("warn", f"🔄 重试 ({_retry+1}/{MAX_RETRIES})...")
                    await _mimic_tiktok_feed(context)
                    await asyncio.sleep(wait_sec)
                    return await scrape_comments(context, video_url, _retry=_retry + 1, max_comments=max_comments, log_fn=log_fn, timeout_ms=timeout_ms)
                else:
                    _log("warn", f"❌ 重试 {MAX_RETRIES} 次后仍无法找到评论元素，跳过该视频。")
                    return comments
        
        print("⏳ 等待评论项渲染...")
        try:
            if item_selector:
                await page.wait_for_selector(item_selector, timeout=timeout_ms)
            else:
                print("⚠️ 没有可用的评论选择器，跳过等待")
        except Exception as e:
            print(f"⚠️ 等待评论选择器超时: {e}")

        # ✅ 核心：检测空评论区 + 自动重试
        if await _is_comment_section_empty(page):
            await page.close()
            if _retry < MAX_RETRIES:
                wait_sec = random.randint(20, 40) * (_retry + 1)
                _log("warn", f"🔄 评论区为空（疑似限流），{wait_sec}s 后重试 ({_retry+1}/{MAX_RETRIES})...")
                await _mimic_tiktok_feed(context)
                await asyncio.sleep(wait_sec)
                return await scrape_comments(context, video_url, _retry=_retry + 1, max_comments=max_comments, log_fn=log_fn, timeout_ms=timeout_ms)
            else:
                _log("warn", f"❌ 重试 {MAX_RETRIES} 次后评论区仍为空，跳过该视频。")
                return comments

        prev_len = 0
        for i in range(MAX_SCROLLS):
            items = page.locator(item_selector)
            await items.first.wait_for(timeout=5000)
            current_count = await items.count()

            for j in range(current_count):
                try:
                    item = items.nth(j)
                    text_val = (await item.locator('span[data-e2e="comment-level-1"]').first.inner_text()).strip()
                    user_href = await item.locator('a[href*="/@"]').first.get_attribute('href')
                    uid = user_href.split('?')[0].split('/')[-1].replace('/@', '')

                    if not any(c['uid'] == uid and c['text'] == text_val for c in comments):
                        comments.append({
                            "uid": uid,
                            "user": uid,
                            "upage": f"https://www.tiktok.com/@{uid}",
                            "text": text_val
                        })
                except Exception as e:
                    print(f"⚠️ 解析第 {j+1} 条评论时出错: {e}")
                    continue

            print(f"🔄 轮次 {i+1}: 捕获到 {len(comments)} 条评论")

            # B：达到评论采集上限即停止（够数即停）
            if max_comments and len(comments) >= max_comments:
                comments = comments[:max_comments]
                _log("info", f"✅ 已达到评论上限 {max_comments} 条，停止滚动")
                break

            if current_count > 0:
                await items.nth(current_count - 1).scroll_into_view_if_needed()
                await page.wait_for_timeout(2000)

            if len(comments) == prev_len:
                print("✅ 确认触底，停止滚动")
                break

            prev_len = len(comments)
            await asyncio.sleep(random.randint(3, 8))

    except Exception as e:
        print(f"❌ 整体运行报错: {e}")
    finally:
        await page.close()
        return comments


async def batch_scrape_comments(context, video_list, max_comments_per_video=None, log_fn=None, timeout_ms=DEFAULT_TIMEOUT):
    """
    批量爬取多个视频评论，供 run.py 调用。
    每 REFRESH_EVERY 个视频主动去首页刷新，防止会话降级导致评论区空白。

    :param max_comments_per_video: 每视频评论采集上限（None=不限制）
    :param log_fn: 可选日志回调 log_fn(level, message)，为 None 时仅走 print。
    :param timeout_ms: 页面操作超时时间(毫秒)，默认60秒
    """

    def _log(level, msg):
        print(msg)
        if log_fn:
            try:
                log_fn(level, msg)
            except Exception:
                pass

    all_results = {}
    total = len(video_list)
    for idx, video_url in enumerate(video_list):
        if idx > 0 and idx % REFRESH_EVERY == 0:
            _log("info", f"🔄 已处理 {idx} 个视频，主动刷新会话状态...")
            await _mimic_tiktok_feed(context)
            sleep_sec = random.randint(30, 60)
            print(f"😴 休息 {sleep_sec}s...")
            await asyncio.sleep(sleep_sec)

        comments = await scrape_comments(context, video_url, max_comments=max_comments_per_video, log_fn=log_fn, timeout_ms=timeout_ms)
        all_results[video_url] = comments
        _log("info", f"✅ [{idx+1}/{total}] 获取 {len(comments)} 条评论: {video_url}")
        await asyncio.sleep(random.randint(10, 25))

    return all_results


async def main():
    USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_TK1"

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        result = await scrape_comments(context, VIDEO_URL)
        print(f"\n🎉 共抓取评论数: {len(result)}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())