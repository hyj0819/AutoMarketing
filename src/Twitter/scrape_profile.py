import argparse
import asyncio
import json
import re
from collections import OrderedDict
from typing import Dict, List, Set, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.async_api import async_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=2160, help="抓取过去N小时内的推文")
    parser.add_argument("--max-post", type=int, default=100, help="最多抓取多少条推文")
    parser.add_argument("--max-idle-scrolls", type=int, default=5, help="无新推文时最多重试滚动次数")
    parser.add_argument("--scroll-delay-ms", type=int, default=2000, help="每次滚动等待的毫秒数")
    parser.add_argument("--headless", action="store_true")

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


# ==========================================
# 2. 核心底层解析函数 (完全保留自您原先的 a.py)
# ==========================================

async def collect_tweet_cards(page, keyword: str, cutoff_date: datetime) -> Tuple[List[Dict], bool]:
    script = """
    async ([keyword, cutoffIso]) => {
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
        await new Promise(r => setTimeout(r, 400));
      }

      // --- 步骤 3：正式开始提取数据 ---
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

        const tweetText = article.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || "";

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
    ret = await page.evaluate(script, [keyword, cutoff_date.isoformat()])
    return ret["results"], ret["shouldStop"]


# ==========================================
# 3. 改造后的主页爬取函数
# ==========================================

async def scrape_user_profile(page, user_url: str, args: argparse.Namespace) -> List[Dict]:
    print(f"\n==================================================")
    print(f"👤 开始爬取用户主页: {user_url}")
    print(f"==================================================")

    # 1. 计算时间截止点
    cutoff_date = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    print(f"⏳ 时间过滤：仅保留 {args.hours} 小时内的帖子 (截止到 {cutoff_date.isoformat()})")

    # 2. 打开用户主页
    try:
        await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"❌ 打开用户主页失败 {user_url}: {e}")
        return []

    # 等待帖子容器加载
    await page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
    await page.wait_for_timeout(args.scroll_delay_ms)

    # 3. 循环滚动页面进行爬取
    all_tweets: Dict[str, Dict] = OrderedDict()
    idle_scrolls = 0
    scrolled_count = 0
    reach_cutoff = False

    while True:
        # 🟢 此时 collect_tweet_cards 已在上方定义，不会再报错
        cards, page_reach_cutoff = await collect_tweet_cards(page, user_url, cutoff_date)
        
        new_found_this_turn = 0
        for card in cards:
            url = card.get("url")
            if not url:
                continue
            
            status_id = extract_status_id(url)
            if status_id not in all_tweets:
                all_tweets[status_id] = card
                new_found_this_turn += 1

        if page_reach_cutoff:
            reach_cutoff = True

        print(f"🔄 滚动第 {scrolled_count+1} 次 | 本轮新抓取: {new_found_this_turn} 条 | 当前总计独有帖子: {len(all_tweets)} 条")

        # 检查是否达到最大限制
        if args.max_post > 0 and len(all_tweets) >= args.max_post:
            print(f"🛑 已达到设定的最大抓取数量限制 (--max-post={args.max_post})，停止。")
            break

        if new_found_this_turn == 0:
            idle_scrolls += 1
        else:
            idle_scrolls = 0

        if idle_scrolls >= args.max_idle_scrolls:
            print(f"🏁 连续 {args.max_idle_scrolls} 次滚动未能加载新帖子，可能已到底部。")
            break

        if reach_cutoff:
            print(f"⏱️ 检测到早于截止时间的帖子，时间条件触发停止。")
            break

        # 微距平滑滚动
        await page.evaluate("window.scrollBy(0, window.innerHeight * 1.2);")
        scrolled_count += 1
        await page.wait_for_timeout(args.scroll_delay_ms)

    # 4. 后期过滤与数据规范化
    results = []
    for status_id, tweet in all_tweets.items():
        try:
            pub_at = parse_published_at(tweet["publishedAt"])
            if pub_at < cutoff_date:
                continue
            
            tweet["replyCount"] = parse_count(tweet.get("replyCountText", "0"))
            tweet["statusId"] = status_id
            results.append(tweet)
        except Exception:
            results.append(tweet)

    print(f"🎉 抓取结束！满足条件的帖子共计: {len(results)} 条")
    
    if args.max_post > 0:
        return results[:args.max_post]
    return results


def deduplicate(items: List[Dict]) -> List[Dict]:
    seen = set()
    unique_items = []
    for item in items:
        uid = item.get("statusId") or extract_status_id(item.get("url", ""))
        if uid not in seen:
            seen.add(uid)
            unique_items.append(item)
    return unique_items


# ==========================================
# 4. 执行入口
# ==========================================

async def main():
    args = parse_args()

    # 🎯 请确保此处的浏览器数据目录路径正确
    USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_1"
    TARGET_USER_URL = "https://x.com/tasi2080"  

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=args.headless,
            viewport={"width": 1440, "height": 1200},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = await context.new_page()
        try:
            tweets = await scrape_user_profile(page, TARGET_USER_URL, args)
            final_tweets = deduplicate(tweets)
            
            print("\n📊 最终抓取结果：")
            print(json.dumps(final_tweets, ensure_ascii=False, indent=2))
            
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(main())