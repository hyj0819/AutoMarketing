import asyncio
from playwright.async_api import async_playwright
import json
import sys
import os
sys.path.append('src/utils')
from common_utils import get_text_response_ds

USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_1" 
TARGET_URL = "https://x.com/lululemon/status/1819126454229389633"
TARGET_URL = "https://x.com/Storage_Venture/status/2042271342649819518"

def parse_target_status_id(url: str) -> str:
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else ""

def build_user_key(item: dict) -> str:
    upage = (item.get("upage") or "").strip().lower()
    uid = (item.get("uid") or "").strip().lower()
    if upage:
        return upage
    if uid:
        return uid
    return (item.get("user") or "").strip().lower()

def build_indent_levels(items, tolerance=12):
    anchors = []
    for item in items:
        indent = item.get("indent", 0)
        matched = False
        for anchor in anchors:
            if abs(anchor - indent) <= tolerance:
                matched = True
                break
        if not matched:
            anchors.append(indent)

    anchors.sort()
    if not anchors:
        return items

    for item in items:
        indent = item.get("indent", 0)
        nearest = min(range(len(anchors)), key=lambda idx: abs(anchors[idx] - indent))
        item["level"] = nearest
    return items

def build_reply_threads(items):
    threads = []
    stack = []

    for item in items:
        level = item.get("level", 0)
        node = {**item, "replies": []}

        while stack and stack[-1]["level"] >= level:
            stack.pop()

        if not stack:
            threads.append(node)
        else:
            stack[-1]["replies"].append(node)

        stack.append(node)

    return threads

def print_reply_threads(threads, depth=0, prefix=""):
    for idx, node in enumerate(threads, start=1):
        label = f"{prefix}{idx}" if prefix else str(idx)
        indent = "    " * depth
        print(
            f"{indent}{label}. {node['user']} ({node['uid']}) | "
            f"主页: {node['upage']} | tweet_id: {node['tweet_id']}"
        )
        print(f"{indent}   内容: {node['text']}")
        if node["replies"]:
            print_reply_threads(node["replies"], depth + 1, f"{label}.")

async def expand_conversation_controls(page):
    clicked = await page.evaluate(
        """() => {
            const primaryColumn = document.querySelector('[data-testid="primaryColumn"]');
            if (!primaryColumn) {
                return 0;
            }

            const patterns = [
                /^show replies$/i,
                /^show more replies$/i,
                /^show more$/i,
                /^more replies$/i
            ];

            let clickedCount = 0;
            const elements = Array.from(
                primaryColumn.querySelectorAll('button, [role="button"], a')
            );

            for (const element of elements) {
                const text = (element.innerText || element.textContent || '')
                    .replace(/\\s+/g, ' ')
                    .trim();
                if (!text || !patterns.some((pattern) => pattern.test(text))) {
                    continue;
                }

                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                if (
                    rect.width === 0 ||
                    rect.height === 0 ||
                    style.display === 'none' ||
                    style.visibility === 'hidden'
                ) {
                    continue;
                }

                element.click();
                clickedCount += 1;
            }

            return clickedCount;
        }"""
    )
    if clicked:
        print(f"🧩 本轮展开了 {clicked} 处折叠回复/更多入口")
        await page.wait_for_timeout(1500)

async def scrape_x_comments(page, target_url, log_dir):
    #page = await context.new_page()
    print(f"🚀 正在访问帖子: {target_url}")
    
    try:
        # 1. 改为 domcontentloaded，只要基础 HTML 渲染完就停止等待 goto
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        
        # 2. 针对 X.com 的动态加载，使用显式等待某个关键元素
        # 这里的 selector 选的是推文正文容器
        print("⏳ 等待评论区渲染...")
        await page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
        
        # 3. 额外给 2 秒缓冲，让回复内容填充
        await page.wait_for_timeout(2000)
        print("👌🏻 页面基础内容已就绪")

    except Exception as e:
        print(f"❌ 加载失败或超时: {e}")
        # 即使超时了，有时页面其实已经打开了，尝试截图看一眼真相
        await page.screenshot(path="timeout_debug.png")
        # 如果截图里有内容，其实可以继续跑，不用 return

    target_status_id = parse_target_status_id(target_url)
    main_post = await page.evaluate(
        """(targetStatusId) => {
            const primaryColumn = document.querySelector('[data-testid="primaryColumn"]');
            if (!primaryColumn) {
                return null;
            }

            const tweets = Array.from(primaryColumn.querySelectorAll('article[data-testid="tweet"]'));
            for (const tweet of tweets) {
                const timeLink = Array.from(tweet.querySelectorAll('a[href*="/status/"]'))
                    .find((a) => a.querySelector('time'));
                const href = timeLink?.getAttribute('href') || '';
                const statusMatch = href.match(/\\/status\\/(\\d+)/);
                const tweetId = statusMatch ? statusMatch[1] : '';
                if (tweetId !== targetStatusId) {
                    continue;
                }

                const text = tweet.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || '';
                const userName = tweet.querySelector('[data-testid="User-Name"]')?.innerText?.trim() || '';
                const profileLink = tweet.querySelector('[data-testid="User-Name"] a[href^="/"]')?.getAttribute('href') || '';
                const infoParts = userName.split('\\n').map((item) => item.trim()).filter(Boolean);
                const username = infoParts.find((item) => item.startsWith('@')) || '';
                const nickname = infoParts[0] || username;

                const timeNode = tweet.querySelector('time');
                const displayTime = timeNode?.innerText || '';
                const fullTimestamp = timeNode?.getAttribute('datetime') || '';

                return {
                    tweet_id: tweetId,
                    user: nickname,
                    uid: username,
                    text,
                    time: displayTime,          // 显示时间，如 "Dec 1, 2025"
                    timestamp: fullTimestamp,   // 精确时间，如 "2025-12-01T10:41:47.000Z"
                    upage: profileLink ? `https://x.com${profileLink}` : (
                        username ? `https://x.com/${username.replace('@', '')}` : ''
                    )
                };
            }
            return null;
        }""",
        target_status_id
    )

    if main_post:
        print("\n📝 主帖信息")
        print(f"{main_post['user']} ({main_post['uid']}) | 主页: {main_post['upage']}")
        print(f"内容: {main_post['text']}\n")

    raw_comments = []
    seen_tweet_ids = set()
    prev_count = 0
    main_tweet_seen = bool(main_post)

    print("📜 正在滚动并实时抓取评论...")


    # 循环滚动抓取，上限 30 次迭代
    for i in range(30):
        try:
            await expand_conversation_controls(page)

            # ... 保持前面代码不变 ...

            comments_batch, main_seen_this_round = await page.evaluate(
                """({ targetStatusId, mainTweetSeen }) => {
                    const primaryColumn = document.querySelector('[data-testid="primaryColumn"]');
                    if (!primaryColumn) {
                        return [[], false];
                    }

                    const cells = Array.from(primaryColumn.querySelectorAll('div[data-testid="cellInnerDiv"]'));
                    const results = [];
                    let sawMainTweetNow = false; 
                    let skipRemaining = false; // 🚩 新增：用于标记是否进入了“Discover more”区域

                    for (const cell of cells) {
                        if (skipRemaining) break; // 如果已经发现“Discover more”，后续内容不再处理

                        // 1. 识别“Discover more”标记
                        // X 通常会有一个特定的文本提示或者 aria-label
                        const cellText = cell.innerText || "";
                        if (cellText.includes("Discover more") || cellText.includes("更多发现")) {
                            skipRemaining = true;
                            continue;
                        }

                        const tweet = cell.querySelector('article[data-testid="tweet"]');
                        if (!tweet) continue;

                        const timeNode = tweet.querySelector('time');
                        const displayTime = timeNode?.innerText || '';
                        const fullTimestamp = timeNode?.getAttribute('datetime') || '';

                        const timeLink = tweet.querySelector('time')?.parentElement;
                        const href = timeLink?.getAttribute('href') || '';
                        const statusMatch = href.match(/\/status\/(\d+)/);
                        const tweetId = statusMatch ? statusMatch[1] : '';

                        if (tweetId === targetStatusId) {
                            sawMainTweetNow = true;
                        }

                        // 2. 备选过滤：通过链接结构过滤
                        // 真正的回复通常会链接回原帖或者在对话流中
                        // 如果 tweetId 为空，通常是广告或推荐，跳过
                        if (!tweetId) continue;

                        const text = tweet.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || '';
                        const userNameNode = tweet.querySelector('[data-testid="User-Name"]');
                        if (!userNameNode) continue;
                        
                        const profileLink = userNameNode.querySelector('a[href^="/"]')?.getAttribute('href') || '';
                        const infoParts = userNameNode.innerText.split('\\n').filter(Boolean);
                        const username = infoParts.find(p => p.startsWith('@')) || '';
                        const nickname = infoParts[0] || '';

                        results.push({
                            tweet_id: tweetId,
                            user: nickname,
                            uid: username,
                            text: text,
                            time: displayTime,        // 提取的时间文本
                            timestamp: fullTimestamp, // 提取的原始时间戳
                            upage: profileLink ? `https://x.com${profileLink}` : (
                                username ? `https://x.com/${username.replace('@', '')}` : ''
                            ),
                            indent: tweet.getBoundingClientRect().left 
                        });
                    }

                    return [results, sawMainTweetNow];
                }""",
                {
                    "targetStatusId": target_status_id,
                    "mainTweetSeen": main_tweet_seen,
                }
            )

            if main_seen_this_round:
                main_tweet_seen = True

            for item in comments_batch:
                tweet_id = item.get("tweet_id")
                if not tweet_id or tweet_id in seen_tweet_ids:
                    continue
                raw_comments.append(item)
                seen_tweet_ids.add(tweet_id)

            print(f"🔄 进度：已抓取 {len(raw_comments)} 条评论/回复")

            # 滚动到最后一个元素以触发懒加载
            tweet_elements = page.locator('[data-testid="primaryColumn"] article[data-testid="tweet"]')
            count = await tweet_elements.count()
            if count > 0:
                await tweet_elements.nth(count - 1).scroll_into_view_if_needed()
                await page.wait_for_timeout(2000) # X 需要一点时间拉取后端数据

            # 停止判定
            if len(raw_comments) == prev_count:
                # 尝试再滚一点，确认真的到底了
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(2000)
                await expand_conversation_controls(page)
                if len(raw_comments) == prev_count:
                    print("👌🏻 评论加载完毕或已达底部")
                    break
            
            prev_count = len(raw_comments)
        except Exception as e:
            print(f'❌出现异常:{e}')
            continue

    raw_comments = build_indent_levels(raw_comments)
    threads = build_reply_threads(raw_comments)

    print(f"\n🎉 抓取结束，共计 {len(raw_comments)} 条评论/回复。下面按顺序展示评论及其回复：\n")
    print_reply_threads(threads)

    
    # 保存结果
    if len(threads) > 0:
        output_file = os.path.join(log_dir, "x_leads.json")
        with open(output_file, "a", encoding="utf-8") as f:
            json.dump(threads, f, indent=4, ensure_ascii=False)

    print(f"\n✅ 调试输出完成\n\n\n")
    #await page.close()

    return raw_comments

async def main():
    target_url = 'https://x.com/stockpickz_hq/status/2057290792864272494'
    log_dir = 'tmp/'

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        # 启动持久化环境
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = await context.new_page()
        raw_comments = await scrape_x_comments(page, target_url, log_dir)

        print(raw_comments)

if __name__ == "__main__":
    asyncio.run(main())