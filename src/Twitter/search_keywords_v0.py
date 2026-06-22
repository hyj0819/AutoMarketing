import argparse
import asyncio
import json
import re
from collections import OrderedDict
from typing import Dict, List, Set, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from playwright.async_api import async_playwright


DEFAULT_KEYWORDS = ["buy stocks"]
DEFAULT_HOURS = 1.5
DEFAULT_MAX_POST = -1
DEFAULT_OUTPUT = Path.cwd() / "output" / "x_search_results.json"
DEFAULT_USER_DATA_DIR = Path("/Users/coast/Desktop/Chrome_Bot_Data_1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape X search results with Playwright.")
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help='Comma-separated keywords, for example: "buy stock,stock analysis"',
    )
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="Keep posts from the last N hours.")
    parser.add_argument("--max-post", type=int, default=DEFAULT_MAX_POST, help="Keep the max posts.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path.")
    parser.add_argument("--user-data-dir", default=str(DEFAULT_USER_DATA_DIR), help="Persistent Playwright profile path.")
    parser.add_argument("--max-idle-scrolls", type=int, default=5, help="Stop after N scrolls with no new tweets.")
    parser.add_argument("--scroll-delay-ms", type=int, default=1800, help="Wait time around each scroll.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument("--search-by-latest", action="store_true", help="latest search or not.")

    return parser.parse_args()



def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    except Exception:
        return url


def parse_count(raw_value: str) -> int:
    if not raw_value:
        return 0

    compact = raw_value.strip().lower().replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)([km]?)$", compact)
    if match:
      value = float(match.group(1))
      suffix = match.group(2)
      if suffix == "k":
          return round(value * 1_000)
      if suffix == "m":
          return round(value * 1_000_000)
      return round(value)

    numeric = re.sub(r"[^\d.]", "", compact)
    try:
        return int(float(numeric)) if numeric else 0
    except ValueError:
        return 0


def extract_status_id(url: str) -> str:
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else url


def parse_published_at(raw_value: str) -> datetime:
    return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))


async def collect_tweet_cards(page, keyword: str, cutoff_date: datetime) -> Tuple[List[Dict], bool]:
    script = """
    async ([keyword, cutoffIso]) => { // 🚩 注意：这里改为 async 函数
      const cutoffTime = new Date(cutoffIso).getTime();

      // --- 步骤 1：先展开所有可见的“Show more” ---
      const articles = document.querySelectorAll('article[data-testid="tweet"]');
      let clickedAny = false;
      
      for (const article of articles) {
        const showMoreBtn = article.querySelector('[data-testid="tweet-text-show-more-link"]');
        if (showMoreBtn) {
          showMoreBtn.click();
          clickedAny = true;
        }
      }

      // --- 步骤 2：如果刚才有点过，等一下 DOM 渲染 ---
      if (clickedAny) {
        await new Promise(r => setTimeout(r, 400)); // 等待 400ms 填充内容
      }

      // --- 步骤 3：正式开始提取数据 ---
      function textFromCandidate(node, selectors) {
        for (const selector of selectors) {
          const candidate = node.querySelector(selector);
          const value = candidate?.textContent?.trim();
          if (value) return value;
        }
        return "";
      }

      function parseCountText(node) {
        const replyButton = node.querySelector('[data-testid="reply"]');
        const directText = replyButton?.textContent?.trim();
        if (directText) return directText;
        const labelled = Array.from(node.querySelectorAll('[aria-label]')).find((item) => {
          const label = item.getAttribute("aria-label") || "";
          return /(repl|reply|回复)/i.test(label);
        });
        return labelled?.getAttribute("aria-label") || "";
      }

      function absoluteUrl(href) {
        if (!href) return "";
        try { return new URL(href, window.location.origin).toString(); } catch { return href; }
      }

      const results = [];
      let shouldStop = false;

      // 再次遍历已存在的 articles 集合
      for (const article of articles) {
        const timeNode = article.querySelector("time");
        const publishedAt = timeNode?.getAttribute("datetime") || "";
        if (!publishedAt) continue;

        const publishedTime = new Date(publishedAt).getTime();
        if (publishedTime < cutoffTime) {
          shouldStop = true;
          break;
        }

        const statusAnchor = timeNode.closest("a") || article.querySelector('a[href*="/status/"]');
        const url = absoluteUrl(statusAnchor?.getAttribute("href") || "");
        if (!url) continue;

        // 🚩 此时读取到的 innerText 已经是展开后的完整内容
        const tweetText = article.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || "";

        // 取 @username：从 User-Name 区域的第一个 <a href="/username"> 提取 href，加 @ 前缀
        const userAnchor = article.querySelector('[data-testid="User-Name"] a[href^="/"]');
        const authorHref = userAnchor?.getAttribute("href") || "";
        const author = authorHref ? "@" + authorHref.replace(/^\//, "").split("/")[0] : "";


        results.push({ 
            keyword, 
            author, 
            publishedAt, 
            url, 
            replyCountText: parseCountText(article),
            text: tweetText 
        });
      }

      return { results, shouldStop };
    }
    """
    # 🚩 注意：调用时使用 evaluate，Playwright 会等待里面的 async 完成
    ret = await page.evaluate(script, [keyword, cutoff_date.isoformat()])
    return ret["results"], ret["shouldStop"]



async def scrape_keyword(page, args: argparse.Namespace) -> List[Dict]:
    keyword = args.keywords
    #page = await context.new_page()
    # 增加过滤条件 f=live 确保是最新的
    search_url = f"https://x.com/search?q={quote(keyword)}&src=typed_query"

    if args.search_by_latest:
        search_url += '&f=live'

    cutoff_date = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    print(f"Searching keyword: {keyword}; search_url:{search_url}")
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    
    try:
        await page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
    except Exception:
        print(f"  ↳ 未能找到帖子，可能是该关键词下暂时没有新内容。")
        await page.close()
        return []

    all_raw_items: List[Dict] = []
    seen_urls: Set[str] = set()
    
    # --- 优化参数 ---
    SCROLL_STEP = 600       # 每次滚动的像素距离（约 1/2 屏）
    MAX_IDLE_TIME = 10      # 累计尝试滚动多少次没有新数据才真正停止
    
    idle_counter = 0
    total_scrolled_dist = 0

    while idle_counter < MAX_IDLE_TIME:
        # 1. 提取当前可见区域的帖子
        raw_items, should_stop = await collect_tweet_cards(page, keyword, cutoff_date)

        # 2. 合并新帖子并实时去重
        initial_count = len(seen_urls)
        for item in raw_items:
            #print(f'item:{item}')
            url_key = normalize_url(item["url"])
            if url_key not in seen_urls:
                seen_urls.add(url_key)
                all_raw_items.append(item)
        
        # 打印当前抓取进度
        if len(seen_urls) > initial_count:
            print(f"  ↳ 目前已收集: {len(all_raw_items)} 条独特帖子...")
            idle_counter = 0 # 只要抓到新的，计数器清零

            if len(all_raw_items) > args.max_post:
                print('  ↳ 已经达到最大数量。')
                break
        else:
            idle_counter += 1

        if should_stop:
            print(f"  ↳ 遇到超出时间范围 ({args.hours}h) 的帖子，停止采集")
            break

        # 3. 优化后的滚动逻辑：微距平滑滚动
        # 模拟真实用户向下滚动 SCROLL_STEP 像素
        await page.evaluate(f"window.scrollBy(0, {SCROLL_STEP})")
        total_scrolled_dist += SCROLL_STEP
        
        # 4. 增加等待：给网络请求和 DOM 渲染留出缓冲期
        # 使用 args.scroll_delay_ms，建议设置在 1500ms - 3000ms 之间
        await page.wait_for_timeout(args.scroll_delay_ms)

        # 每隔 3 次滚动，额外做一个 Network Idle 检查，确保数据包已接收
        if idle_counter % 3 == 0:
            try:
                # 缩短超时时间，避免因个别图片加载慢而卡住
                await page.wait_for_load_state("networkidle", timeout=3000)
            except:
                pass

        # 5. 检查是否真的到底了（如果滚动了很久高度都不变）
        current_max_height = await page.evaluate("document.body.scrollHeight")
        if total_scrolled_dist > current_max_height + 2000: # 容错余量
            print("  ↳ 已经滚动至页面底端。")
            break

    #await page.close()

    # 后续处理：过滤评论数为 0 的帖子
    results: List[Dict] = []
    for item in all_raw_items:
        reply_count = parse_count(item.get("replyCountText", ""))
        if reply_count <= 0:
            continue
        results.append(
            {
                "keyword": item.get("keyword", keyword),
                "author": item.get("author", ""),
                "publishedAt": item["publishedAt"],
                "url": normalize_url(item["url"]),
                "replyCount": reply_count,
                "text": item.get("text", "")
            }
        )

    return results


def deduplicate(items: List[Dict]) -> List[Dict]:
    seen: OrderedDict = OrderedDict()

    for item in items:
        key = extract_status_id(item["url"])
        existing = seen.get(key)
        if not existing:
            seen[key] = item
            continue

        if parse_published_at(item["publishedAt"]) > parse_published_at(existing["publishedAt"]):
            seen[key] = item

    return sorted(seen.values(), key=lambda item: parse_published_at(item["publishedAt"]), reverse=True)


async def main() -> None:
    args = parse_args()
    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    output_path = Path(args.output).resolve()
    user_data_dir = Path(args.user_data_dir).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args.search_by_latest = False
    args.max_idle_scrolls = 1
    args.hours = 2160
    print(f'args:{args}')

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            channel="chrome",
            headless=args.headless,
            viewport={"width": 1440, "height": 1200},
        )
        page = await context.new_page()
        try:
            all_items: List[Dict] = []
            for keyword in keywords:
                items = await scrape_keyword(page, args)
                all_items.extend(items)

            deduplicated = deduplicate(all_items)
            payload = {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "filters": {
                    "keywords": keywords,
                    "hours": args.hours,
                    "replyCountGreaterThan": 0,
                },
                "totalBeforeDeduplication": len(all_items),
                "totalAfterDeduplication": len(deduplicated),
                "results": deduplicated,
            }
            print(f'deduplicated:{deduplicated}')
            #output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            #print(f"Saved {len(deduplicated)} unique posts to {output_path}")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())