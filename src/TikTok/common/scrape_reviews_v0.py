import asyncio
from playwright.async_api import async_playwright
import json, random

VIDEO_URL = "https://www.tiktok.com/@stastclkstocks/video/7641767208036896013"
MAX_SCROLLS = 10
MAX_RETRIES = 2          # 检测到空评论区时的最大重试次数
REFRESH_EVERY = 10       # 每爬取 N 个视频后去首页刷一刷，重置会话状态


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
    ]
    for sel in empty_indicators:
        try:
            if await page.locator(sel).count() > 0:
                print(f"⚠️ 检测到评论区空状态占位符: {sel}")
                return True
        except Exception:
            pass

    # 兜底：等 3s 后仍然没有任何评论项，视为空
    try:
        await page.wait_for_selector('div[class*="DivCommentObjectWrapper"]', timeout=3000)
        return False
    except Exception:
        return True


async def scrape_comments(context, video_url, _retry=0):
    """
    爬取单个视频评论。
    遇到空评论区时自动重试（最多 MAX_RETRIES 次），
    重试前去首页拟人浏览以重置会话状态。
    """
    page = await context.new_page()
    await page.set_viewport_size({"width": 1280, "height": 800})
    print(f"🚀 正在打开 (retry={_retry}): {video_url}")

    comments = []
    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        # 点击评论图标展开评论区
        comment_icon_btn = page.locator('button').filter(
            has=page.locator('span[data-e2e="comment-icon"]')
        )
        await comment_icon_btn.first.click()
        await page.wait_for_timeout(2000)

        item_selector = 'div[class*="DivCommentObjectWrapper"]'
        print("⏳ 等待评论项渲染...")
        try:
            await page.wait_for_selector(item_selector, timeout=10000)
        except Exception:
            pass  # 超时后继续走空状态检测

        # ✅ 核心：检测空评论区 + 自动重试
        if await _is_comment_section_empty(page):
            await page.close()
            if _retry < MAX_RETRIES:
                wait_sec = random.randint(20, 40) * (_retry + 1)
                print(f"🔄 评论区为空（疑似限流），{wait_sec}s 后重试 ({_retry+1}/{MAX_RETRIES})...")
                await _mimic_tiktok_feed(context)
                await asyncio.sleep(wait_sec)
                return await scrape_comments(context, video_url, _retry=_retry + 1)
            else:
                print(f"❌ 重试 {MAX_RETRIES} 次后评论区仍为空，跳过该视频。")
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


async def batch_scrape_comments(context, video_list):
    """
    批量爬取多个视频评论，供 run.py 调用。
    每 REFRESH_EVERY 个视频主动去首页刷新，防止会话降级导致评论区空白。
    """
    all_results = {}
    for idx, video_url in enumerate(video_list):
        if idx > 0 and idx % REFRESH_EVERY == 0:
            print(f"\n🔄 已处理 {idx} 个视频，主动刷新会话状态...")
            await _mimic_tiktok_feed(context)
            sleep_sec = random.randint(30, 60)
            print(f"😴 休息 {sleep_sec}s...")
            await asyncio.sleep(sleep_sec)

        comments = await scrape_comments(context, video_url)
        all_results[video_url] = comments
        print(f"✅ [{idx+1}/{len(video_list)}] {video_url} → {len(comments)} 条评论\n")
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