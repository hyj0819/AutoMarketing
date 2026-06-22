import asyncio
import json
from playwright.async_api import async_playwright
from src.utils.common_utils import get_text_response_ds, parse_cookie_string



USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data" 

async def scrape_tradingview_fully(keyword):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False
        )
        page = context.pages[0] if context.pages else await context.new_page()

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        
        # 切换“所有评论”逻辑... (保留你原来的代码)

        final_comments = []
        seen_texts = set()
        prev_count = 0
        
        # 定义需要点击的“加载更多”关键词（支持多语言）
        load_more_selectors = [
            "View more comments", 
            "View previous comments", 
            "Write a reply",
            "See more",
            "查看更多评论",
            "显示以前的评论"
        ]

        for i in range(50):
            # 1. 尝试寻找并点击所有的“查看更多”或“更多回复”
            for text in load_more_selectors:
                try:
                    # 使用 get_by_text 寻找页面上所有匹配的按钮
                    buttons = page.get_by_text(text, exact=False)
                    count = await buttons.count()
                    for idx in range(count):
                        btn = buttons.nth(idx)
                        if await btn.is_visible():
                            await btn.click()
                            # 点击后给一点缓冲时间
                            await page.wait_for_timeout(1500) 
                except:
                    continue

            # 2. 模拟真实人类向下滚动
            # 不要一次性滚到底，每次滚 1000 像素
            await page.mouse.wheel(0, 1000)
            await page.wait_for_timeout(2000) # 等待网络请求

            # 2. 增强版解析逻辑
            comment_blocks = page.locator('div[role="article"]')
            current_count = await comment_blocks.count()
            
            for j in range(current_count):
                try:
                    block = comment_blocks.nth(j)
                    text_node = block.locator('div[dir="auto"]').first
                    content = await text_node.inner_text()

                    if content and content not in seen_texts:
                        # 定位作者：寻找 role=link 且内部包含文本的元素
                        # 优先寻找包含 strong 标签的 link (这是 FB 名字的标准结构)
                        author_node = block.locator('a[role="link"]').filter(has_text="").nth(0)
                        
                        # 兜底逻辑：如果第一个 link 是空的（多为头像），找有文字的那个
                        for link_idx in range(await block.locator('a[role="link"]').count()):
                            name_candidate = await block.locator('a[role="link"]').nth(link_idx).inner_text()
                            if name_candidate.strip():
                                author_node = block.locator('a[role="link"]').nth(link_idx)
                                break

                        author_name = await author_node.inner_text()
                        raw_href = await author_node.get_attribute("href")
                        
                        # 清洗 URL
                        clean_url = "None"
                        if raw_href:
                            clean_url = raw_href.split('?')[0].split('&')[0]
                            if clean_url.startswith('/'):
                                clean_url = f"https://www.facebook.com{clean_url}"

                        final_comments.append({
                            "user": author_name.strip(),
                            "text": content.strip(),
                            "profile_url": clean_url
                        })
                        seen_texts.add(content)
                except:
                    continue

            print(f"🔄 迭代 {i+1}: 已抓取 {len(final_comments)} 条")
            
            # 滚动逻辑：寻找“View more comments”按钮或直接滚动
            more_btn = page.get_by_text("View more comments", exact=False)
            if await more_btn.is_visible():
                await more_btn.click()
                await page.wait_for_timeout(2000)
            else:
                # 模拟鼠标向下滚动触发懒加载
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(2000)

            if len(final_comments) == prev_count: break
            prev_count = len(final_comments)

        # 保存结果
        with open("fb_comments.json", "w", encoding="utf-8") as f:
            json.dump(final_comments, f, indent=4, ensure_ascii=False)

        print(f"\n🎉 抓取结束，共计 {len(final_comments)} 条评论。")

        # --- AI 判定逻辑 ---
        potential_customers = []
        for c in final_comments:
            prompt = f"Analyze this tweet reply: '{c['text']}'. Does this person show interest in buying or wearing the product (Lululemon)? Reply only 'yes' or 'no'."
            system_msg = "You are a lead generation expert. Be concise."
            
            try:
                ret = get_text_response_ds(prompt, system_msg).lower().strip()
                if 'yes' in ret:
                    print(f"🎯 潜在客户: {c['user']} ({c['profile_url']}) | 内容: {c['text']}...")
                    potential_customers.append(c)
            except:
                continue

        await context.close()

if __name__ == "__main__":
    asyncio.run(scrape_facebook_comments())