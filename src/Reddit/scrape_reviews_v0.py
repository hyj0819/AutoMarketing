import asyncio
from playwright.async_api import async_playwright
import sys, requests
sys.path.append('./src/utils')
from common_utils import get_text_response_ds, parse_cookie_string, get_adspower_ws

USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"

async def scrape_reddit_comments(page, url):
    print(f"正在访问: {url}")
    await page.goto(url, wait_until="domcontentloaded")

    # 提取文章内容
    post_content = await page.locator('div[class="text-neutral-content"]').inner_text()
    #print(f'post_content:{post_content}')

    # --- 功能 1: 自动滚动并点击“加载更多” ---
    print("开始深度加载评论...")
    previous_count = 0
    no_growth_steps = 0  # 统计数量没有增长的次数
    max_no_growth = 3  # 最大重试次数，防止卡死
    
    while no_growth_steps < max_no_growth:
        # 1. 强制滚动到底部
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # 给予足够的网络和渲染时间
        await asyncio.sleep(20) 

        # 2. 寻找加载按钮（增加对 "Show more replies" 的支持）
        # Reddit 常见的几种加载按钮标识
        more_buttons_selectors = [
            'button:has-text("View more comments")',
            'button:has-text("more")',
            'faceplate-batch:has-text("more")',
            'shreddit-comment-tree-more'
        ]
        
        found_buttons = False
        for selector in more_buttons_selectors:
            buttons = page.locator(selector)
            count = await buttons.count()
            for i in range(count):
                try:
                    btn = buttons.nth(i)
                    if await btn.is_visible() and await btn.is_enabled():
                        # 使用 dispatch_event 触发点击，有时比直接 click 更稳
                        await btn.dispatch_event("click")
                        found_buttons = True
                except:
                    continue
        
        # 3. 计算当前评论数
        current_count = await page.locator('shreddit-comment').count()
        print(f"当前已加载评论数: {current_count} (重试计数: {no_growth_steps}/{max_no_growth})")

        # 4. 判断跳出条件
        if current_count > previous_count:
            no_growth_steps = 0  # 只要有增长，重置重试计数
            previous_count = current_count
        else:
            # 即使数量没变，如果刚才点击了按钮，可能还在加载中，再给一次机会
            if found_buttons:
                await asyncio.sleep(2)
            no_growth_steps += 1
            
    print("停止加载：已达到最大重试次数或内容已全部加载。")

    # --- 功能 2: 精确解析评论内容 ---
    comments_data = []
    comment_elements = await page.locator('shreddit-comment').all()

    for comment in comment_elements:
        # 1. 解析昵称 (Author)
        author = await comment.get_attribute('author') or "[deleted]"
        
        # 2. 解析深度 (Depth)
        depth_str = await comment.get_attribute('depth') or "0"
        depth = int(depth_str)

        # 3. 生成主页链接 (Profile URL)
        # Reddit 用户主页标准格式为 https://www.reddit.com/user/用户名
        profile_url = f"https://www.reddit.com/user/{author}" if author != "[deleted]" else "N/A"

        # 4. 精确解析内容 (Content)
        # 这里的 xpath 逻辑做了微调，确保只抓取当前层级文本
        content = ""
        # 尝试定位内容容器
        content_container = comment.locator('xpath=./div[@id and contains(@id, "-content")]').first
        
        if await content_container.count() > 0:
            # 优先寻找包含 md 样式的 div (富文本内容)
            rich_text = content_container.locator('xpath=./div[contains(@class, "md")]').first
            if await rich_text.count() > 0:
                content = await rich_text.inner_text()
            else:
                # 添加 await
                paragraphs = await content_container.locator('xpath=.//p').all()

                # 现在 paragraphs 是一个真正的列表，可以安全地进行列表推导
                p_texts = [await p.inner_text() for p in paragraphs]
                content = " ".join(p_texts)
        
        # 5. 组装数据
        item = {
            "comment_author": author,
            "profile_url": profile_url,
            "comment_content": content.strip().replace('\n', ' '),
            "depth": depth,
            "post_content": post_content.strip().replace('\n', ' ')
        }
        #print(f'item:{item}')
        comments_data.append(item)

    print(f"\n🎉 抓取完成！总计: {len(comments_data)} 条评论")

    return comments_data


async def main():
    target_url = "https://www.reddit.com/r/politics/comments/1skwe1n/vance_says_pope_leo_should_stay_out_of_us_affairs/"
    target_url = "https://www.reddit.com/r/politics/comments/1skwe1n/vance_says_pope_leo_should_stay_out_of_us_affairs/"
    target_url = "https://www.reddit.com/r/Golfsimulator/comments/1t6pvr9/golf_sim_acquired/"
    target_url = "https://www.reddit.com/r/Golfsimulator/comments/1t9bxmb/turning_my_root_infested_nightmare_into_a_golf_sim/"
    target_url = "https://www.reddit.com/r/Golfsimulator/comments/1tg1pv2/suggestions_on_launch_monitor/"
    #target_url = "https://www.reddit.com/r/investingforbeginners/comments/1tfhqst/new_to_investing/"

    USE_CHROME = False

    async with async_playwright() as p:
        # 启动持久化环境
        if USE_CHROME:
            context = await p.chromium.launch_persistent_context(
                USER_DATA_DIR,
                channel="chrome",
                headless=False,
                no_viewport=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
        else:
            ws_endpoint = get_adspower_ws()
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0]

        page = context.pages[0]
        results = await scrape_reddit_comments(page, target_url)

        for r in results:
            # 打印调试信息
            indent = "  " * r['depth']
            print(f"{indent}👤 {r['comment_author']} | 🔗 {r['profile_url']} | 🔖 {r['comment_content']}")

        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
    
