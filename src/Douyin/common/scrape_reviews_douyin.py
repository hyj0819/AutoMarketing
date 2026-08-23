from __future__ import annotations
import asyncio
import re
import random
from typing import Callable, Optional
from playwright.async_api import BrowserContext, Page

MAX_SCROLLS = 10
MAX_RETRIES = 2
REFRESH_EVERY = 10
DEFAULT_TIMEOUT = 60000
COMMENT_BUTTON_WAIT_TIMEOUT = 15000

COMMENT_ITEM_SELECTORS = (
    'div[data-e2e="comment-item"]',
    'div[class*="DivCommentItem"]',
    'div[class*="CommentItem"]',
)
COMMENT_TEXT_SELECTORS = (
    'span[data-e2e="comment-level-1"]',
    '[data-e2e="comment-text"]',
    'div[data-e2e="comment-level-1"]',
    'span[class*="comment-text"]',
    'p[class*="comment"]',
)
COMMENT_EMPTY_SELECTORS = (
    'p[data-e2e="comment-empty-text"]',
    '[data-e2e="comment-empty"]',
)
# 视频页面评论按钮（侧边栏图标）+ 评论区展开按钮
COMMENT_BUTTON_SELECTORS = (
    '[data-e2e="feed-comment-icon"]',
    'button[data-e2e="comment"]',
    'div[role="button"][data-e2e="comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[role="button"][aria-label*="评论"]',
)


async def _find_visible_locator(page: Page, selectors: tuple[str, ...]):
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if await candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return None


async def _click_comment_button(page: Page, timeout_ms: int) -> bool:
    candidates = page.locator(", ".join(COMMENT_BUTTON_SELECTORS))
    try:
        await candidates.wait_for(
            state="visible",
            timeout=min(timeout_ms, COMMENT_BUTTON_WAIT_TIMEOUT),
        )
    except Exception:
        pass

    button = await _find_visible_locator(page, COMMENT_BUTTON_SELECTORS)
    if button is None:
        return False

    try:
        await button.click(timeout=timeout_ms)
        return True
    except Exception as exc:
        print(f"Could not click the comment button: {exc}")
        return False


def _append_comment(comments: list[dict], seen: set[tuple[str, str]], uid: str, text: str) -> None:
    uid = str(uid or "").lstrip("@").strip()
    text = str(text or "").strip()
    if not uid or not text or uid == "unknown":
        return
    key = (uid, text)
    if key in seen:
        return
    seen.add(key)
    comments.append({
        "uid": uid,
        "user": uid,
        "upage": f"https://www.douyin.com/user/{uid}",
        "text": text,
    })


async def _collect_dom_comments(page: Page, comments: list[dict], seen: set[tuple[str, str]]) -> int:
    before = len(comments)
    for item_selector in COMMENT_ITEM_SELECTORS:
        items = page.locator(item_selector)
        count = await items.count()
        if not count:
            continue
        for index in range(count):
            item = items.nth(index)
            try:
                # 尝试多种选择器提取评论文本
                text = ""
                text_elem = await _find_visible_locator(item, COMMENT_TEXT_SELECTORS)
                if text_elem:
                    text = (await text_elem.inner_text()).strip()

                # 回退：从评论项中提取文本，过滤掉按钮和元数据
                if not text:
                    try:
                        full_text = await item.inner_text()
                        # 过滤掉常见的 UI 文本
                        lines = full_text.split('\n')
                        text_lines = []
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            # 跳过常见的 UI 元素文本
                            if line in ('分享', '回复', '展开', '...', '收起'):
                                continue
                            if '月前' in line or '天前' in line or '小时前' in line or '刚刚' in line:
                                continue
                            if re.match(r'^\d+$', line):  # 纯数字（点赞数）
                                continue
                            text_lines.append(line)
                        text = ' '.join(text_lines).strip()
                    except Exception:
                        pass

                if not text:
                    continue

                user_link = item.locator('a[href*="/user/"]').first
                href = await user_link.get_attribute("href") if await user_link.count() else ""
                if not href:
                    continue

                match = re.search(r"/user/([^/?]+)", href)
                if match:
                    _append_comment(comments, seen, match.group(1), text)
            except Exception as exc:
                print(f"Could not parse comment #{index + 1}: {exc}")
    return len(comments) - before


async def _has_visible_empty_state(page: Page) -> bool:
    for selector in COMMENT_EMPTY_SELECTORS:
        locator = page.locator(selector)
        if await locator.count() and await locator.first.is_visible():
            return True
    return False


async def _scrape_comments_once(
    context: BrowserContext,
    video_url: str,
    max_comments: Optional[int],
    timeout_ms: int,
    log: Callable[[str, str], None],
) -> tuple[list[dict], str]:
    page = await context.new_page()
    comments: list[dict] = []
    seen: set[tuple[str, str]] = set()

    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(4000)

        # 先检查评论是否已经直接加载在页面上（抖音视频页右侧面板）
        existing_items = page.locator('div[data-e2e="comment-item"]')
        existing_count = await existing_items.count()

        if existing_count > 0:
            log("info", f"评论区已直接加载，检测到 {existing_count} 条评论")
        else:
            # 评论未直接显示，尝试点击评论按钮展开
            log("info", "评论未直接显示，尝试点击评论按钮...")
            if not await _click_comment_button(page, timeout_ms):
                log("warn", "Could not find a visible Douyin comment button.")
                return comments, "unavailable"
            await page.wait_for_timeout(3500)

        await _collect_dom_comments(page, comments, seen)

        no_growth_rounds = 0
        previous_count = len(comments)
        for _ in range(MAX_SCROLLS):
            if max_comments and len(comments) >= max_comments:
                return comments[:max_comments], "success"

            # 滚动评论区加载更多
            items = page.locator(", ".join(COMMENT_ITEM_SELECTORS))
            count = await items.count()
            if count:
                await items.nth(count - 1).scroll_into_view_if_needed()
            else:
                await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(1800)
            await _collect_dom_comments(page, comments, seen)

            if len(comments) == previous_count:
                no_growth_rounds += 1
                if no_growth_rounds >= 2:
                    break
            else:
                no_growth_rounds = 0
                previous_count = len(comments)

        if comments:
            return comments[:max_comments] if max_comments else comments, "success"
        if await _has_visible_empty_state(page):
            return comments, "empty"
        return comments, "unavailable"
    except Exception as exc:
        log("error", f"Comment scraping failed: {exc}")
        return comments, "unavailable"
    finally:
        await page.close()


async def scrape_comments(
    context: BrowserContext,
    video_url: str,
    _retry: int = 0,
    max_comments: Optional[int] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
    timeout_ms: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    def log(level: str, message: str) -> None:
        print(message)
        if log_fn:
            try:
                log_fn(level, message)
            except Exception:
                pass

    for attempt in range(_retry, MAX_RETRIES + 1):
        log("info", f"Opening comments (attempt {attempt + 1}/{MAX_RETRIES + 1}): {video_url}")
        comments, state = await _scrape_comments_once(context, video_url, max_comments, timeout_ms, log)
        if state == "success":
            log("info", f"Collected {len(comments)} comments.")
            return comments
        if state == "empty":
            log("info", "Douyin reports that this video has no comments.")
            return []
        if attempt == MAX_RETRIES:
            log("warn", "Comments were unavailable after retries; skipping this video.")
            return comments

        wait_seconds = random.randint(15, 25) * (attempt + 1)
        log("warn", f"Comments did not load; retrying in {wait_seconds}s.")
        await asyncio.sleep(wait_seconds)

    return []


async def batch_scrape_comments(
    context: BrowserContext,
    video_list: list[str],
    max_comments_per_video: Optional[int] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
    timeout_ms: int = DEFAULT_TIMEOUT,
) -> dict[str, list[dict]]:
    def log(level: str, message: str) -> None:
        print(message)
        if log_fn:
            try:
                log_fn(level, message)
            except Exception:
                pass

    all_results: dict[str, list[dict]] = {}
    for index, video_url in enumerate(video_list):
        comments = await scrape_comments(
            context, video_url,
            max_comments=max_comments_per_video,
            log_fn=log_fn,
            timeout_ms=timeout_ms,
        )
        all_results[video_url] = comments
        log("info", f"[{index + 1}/{len(video_list)}] Collected {len(comments)} comments: {video_url}")
        await asyncio.sleep(random.randint(8, 15))
    return all_results


async def main() -> None:
    from playwright.async_api import async_playwright

    user_data_dir = "/Users/hyj/Documents/mywork/AutoMarketing/chrome_data/Chrome_Bot_Data_DY"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        VIDEO_URL = "https://www.douyin.com/video/7401234567890123456"
        comments = await scrape_comments(context, VIDEO_URL, max_comments=10)
        print(f"共采集到 {len(comments)} 条评论")
        for c in comments:
            print(f"  {c['uid']}: {c['text'][:50]}")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())