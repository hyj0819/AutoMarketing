from __future__ import annotations

import asyncio
import re
import random
from typing import Callable, Optional

from playwright.async_api import BrowserContext, Page


VIDEO_URL = "https://www.tiktok.com/@stastclkstocks/video/7641767208036896013"
MAX_SCROLLS = 10
MAX_RETRIES = 2
REFRESH_EVERY = 10
DEFAULT_TIMEOUT = 60000
COMMENT_BUTTON_WAIT_TIMEOUT = 15000

COMMENT_ITEM_SELECTORS = (
    'div[data-e2e="comment-item"]',
    'div[class*="DivCommentObjectWrapper"]',
    'div[class*="DivCommentItemWrapper"]',
    'div[class*="CommentItem"]',
)
COMMENT_TEXT_SELECTORS = (
    'span[data-e2e="comment-level-1"]',
    'div[data-e2e="comment-level-1"]',
    '[data-e2e="comment-text"]',
)
COMMENT_EMPTY_SELECTORS = (
    'p[data-e2e="comment-empty-text"]',
    '[data-e2e="comment-empty"]',
    'text="Start the conversation"',
    'text="Be the first to comment"',
)
COMMENT_BUTTON_SELECTORS = (
    'div[role="button"][data-e2e="comment-icon"]',
    '[data-e2e="browse-comment"]',
    '[data-e2e="comment-icon"]',
    'button[data-e2e="comment"]',
    'button:has(span[data-e2e="comment-icon"])',
    'button[aria-label*="comment" i]',
    '[role="button"][aria-label*="comment" i]',
    '[role="button"][aria-label*="评论"]',
)


async def _mimic_tiktok_feed(context: BrowserContext) -> None:
    """Briefly browse the feed before retrying a failed comment request."""
    page = await context.new_page()
    try:
        print("[Session refresh] Browsing the TikTok feed before retrying...")
        await page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(3, 6))
        for _ in range(random.randint(2, 4)):
            await page.mouse.wheel(0, random.randint(500, 1000))
            await asyncio.sleep(random.uniform(1.5, 3))
    except Exception as exc:
        print(f"[Session refresh] Failed: {exc}")
    finally:
        await page.close()


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
    """Click an explicitly identified comment control, never a generic icon button."""
    # The video shell is visible before TikTok mounts the action rail. Do not infer
    # failure from the first DOM snapshot; wait for a known comment control instead.
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
        "upage": f"https://www.tiktok.com/@{uid}",
        "text": text,
    })


def _extract_api_comments(payload: object, comments: list[dict], seen: set[tuple[str, str]]) -> int:
    """Extract comments from TikTok's comment-list response without relying on CSS classes."""
    if not isinstance(payload, dict):
        return 0

    raw_comments = payload.get("comments")
    if not isinstance(raw_comments, list):
        return 0

    before = len(comments)
    for raw_comment in raw_comments:
        if not isinstance(raw_comment, dict):
            continue
        user = raw_comment.get("user") or {}
        if not isinstance(user, dict):
            user = {}
        uid = user.get("unique_id") or user.get("uniqueId") or user.get("user_id")
        text = raw_comment.get("text") or raw_comment.get("comment_description")
        _append_comment(comments, seen, uid, text)
    return len(comments) - before


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
                text_locator = await _find_visible_locator(item, COMMENT_TEXT_SELECTORS)
                user_link = item.locator('a[href*="/@"]').first
                href = await user_link.get_attribute("href")
                if text_locator is None or not href:
                    continue
                match = re.search(r"/@([^/?]+)", href)
                if match:
                    _append_comment(comments, seen, match.group(1), await text_locator.inner_text())
            except Exception as exc:
                print(f"Could not parse comment #{index + 1}: {exc}")
        # A page can match more than one fallback selector; deduplication handles overlap.
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
    """Return comments plus a result state: success, empty, or unavailable."""
    page = await context.new_page()
    comments: list[dict] = []
    seen: set[tuple[str, str]] = set()

    async def capture_comment_response(response) -> None:
        # TikTok's API is less volatile than the rendered class names. Only accept its comment-list endpoint.
        if "/api/comment/list" not in response.url.lower():
            return
        try:
            _extract_api_comments(await response.json(), comments, seen)
        except Exception:
            pass

    page.on("response", capture_comment_response)
    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(2500)

        if not await _click_comment_button(page, timeout_ms):
            log("warn", "Could not find a visible TikTok comment button.")
            return comments, "unavailable"

        # The click triggers the first /api/comment/list request. Waiting for it is more reliable than
        # deciding from the DOM immediately after the click.
        await page.wait_for_timeout(3500)
        await _collect_dom_comments(page, comments, seen)

        no_growth_rounds = 0
        previous_count = len(comments)
        for _ in range(MAX_SCROLLS):
            if max_comments and len(comments) >= max_comments:
                return comments[:max_comments], "success"

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
    """Scrape comments for one video, retrying only transient unavailable states."""
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
            log("info", "TikTok reports that this video has no comments.")
            return []
        if attempt == MAX_RETRIES:
            log("warn", "Comments were unavailable after retries; skipping this video.")
            return comments

        wait_seconds = random.randint(15, 25) * (attempt + 1)
        log("warn", f"Comments did not load; refreshing the session and retrying in {wait_seconds}s.")
        await _mimic_tiktok_feed(context)
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
        if index and index % REFRESH_EVERY == 0:
            log("info", f"Refreshing session after {index} videos.")
            await _mimic_tiktok_feed(context)
            await asyncio.sleep(random.randint(20, 35))

        comments = await scrape_comments(
            context,
            video_url,
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

    user_data_dir = "/Users/hyj/Documents/mywork/AutoMarketing/chrome_data/Chrome_Bot_Data_TK"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        comments = await scrape_comments(context, VIDEO_URL)
        print(comments)
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
