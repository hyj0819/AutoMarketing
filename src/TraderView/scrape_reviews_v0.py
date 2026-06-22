import asyncio
from playwright.async_api import async_playwright

async def scrape_tradingview_comments(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()
        
        print(f"\t正在打开页面: {url}")
        await page.goto(url, wait_until="domcontentloaded")

        # 1. 逐步下拉，直到评论区容器加载
        # 使用模糊匹配选择器 [class*="commentList"]
        comment_container_selector = '[class*="commentList"]'
        print("\t正在探测评论区，尝试滚动加载...")
        
        max_retries = 20
        found = False
        for _ in range(max_retries):
            # 检查容器是否已经在 DOM 中
            container = page.locator(comment_container_selector).first
            if await container.count() > 0 and await container.is_visible():
                print("\t找到评论区！")
                found = True
                break
            # 每次向下滚动 800 像素
            await page.mouse.wheel(0, 800)
            await asyncio.sleep(0.5)
        
        if not found:
            print("\t未能定位到评论区，请检查页面结构。")
            await browser.close()
            return {}

        # 2. 展开所有隐藏回复
        print("\t开始递归展开回复内容...")
        # 匹配包含 "loadMore" 或 "showMore" 字样的类名，以及按钮文本
        btn_selector = 'button:has-text("more replies"), button:has-text("Show more"), [class*="loadMore"]'
                
        while True:
            # 重新获取当前可见的按钮
            btns = page.locator(btn_selector)
            count = await btns.count()
            
            # 过滤出真正可见且可以点击的按钮
            target_btn = None
            for i in range(count):
                b = btns.nth(i)
                if await b.is_visible() and await b.is_enabled():
                    target_btn = b
                    break
            
            if not target_btn:
                print("\t没有更多可展开的按钮了。")
                break
            
            try:
                # 获取按钮文本用于调试日志
                btn_text = await target_btn.inner_text()
                print(f"\t正在点击: {btn_text.strip()}")
                
                # 滚动到按钮并点击
                await target_btn.scroll_into_view_if_needed()
                await target_btn.click(force=True)
                
                # 重要：等待数据加载的短延时
                await asyncio.sleep(1.2) 
            except Exception as e:
                print(f"\t点击按钮出错（可能已消失）: {e}")
                break

        # 3. 提取帖子作者信息
        print("\t正在提取帖子作者信息...")
        author_info = {"username": "Unknown", "profile_url": ""}
        
        try:
            # 使用你提供的源码特征进行模糊匹配
            author_container = page.locator('[class*="author-"]').first
            if await author_container.count() > 0:
                # 寻找包含 /u/ 的链接
                author_link_el = author_container.locator('a[href^="/u/"]').first
                # 寻找用户名 div
                author_name_el = author_container.locator('[class*="username-"]').first
                
                if await author_link_el.count() > 0:
                    href = await author_link_el.get_attribute('href')
                    author_info["profile_url"] = f"https://www.tradingview.com{href}" if href else ""
                
                if await author_name_el.count() > 0:
                    author_info["username"] = (await author_name_el.inner_text()).strip()
        except Exception as e:
            print(f"\t❌提取作者信息时出错: {e}")

        # 4. 数据提取
        print("\t正在提取所有评论及用户主页链接...")
        card_selector = 'div[data-name="comment-card"]'
        comment_cards = await page.locator(card_selector).all()
        
        base_url = "https://www.tradingview.com"
        results = []
        
        for card in comment_cards:
            try:
                # 定位用户名元素，它通常是一个 <a> 标签
                user_link_el = card.locator('a[class*="username"]').first
                content_el = card.locator('[class*="content-"]').first
                time_el = card.locator('[class*="time-"]').first
                
                # 提取用户名
                username = await user_link_el.inner_text() if await user_link_el.count() > 0 else "Unknown"
                
                # 提取主页链接 (href)
                user_profile = ""
                if await user_link_el.count() > 0:
                    href = await user_link_el.get_attribute('href')
                    if href:
                        # 如果是相对路径则拼接，如果是绝对路径则直接使用
                        user_profile = href if href.startswith('http') else f"{base_url}{href}"

                # 提取内容和时间
                content = await content_el.inner_text() if await content_el.count() > 0 else ""
                time_str = await time_el.get_attribute('title') if await time_el.count() > 0 else ""
                
                # 识别是否是回复
                class_attr = await card.get_attribute("class")
                is_reply = "nested" in class_attr if class_attr else False

                results.append({
                    "username": username.strip(),
                    "profile_url": user_profile, # 新增字段
                    "time": time_str,
                    "content": content.strip(),
                    "type": "Reply" if is_reply else "Primary"
                })
            except Exception as e:
                print(f"\t解析单条评论出错: {e}")
                continue
            

        print(f"\t✅抓取完成，共获得 {len(results)} 条评论。")
        await browser.close()

        # 返回一个包含作者和评论列表的字典
        return {
            "post_author": author_info,
            "comments": results
        }

# 启动
if __name__ == "__main__":
    url = "https://www.tradingview.com/chart/BTCUSDT/fiTFLfEh-Bitcoin-LifeTime-Opportunity-right-now-watch-this/"
    url = "https://www.tradingview.com/script/a5EsBAmo-Stock-Value-How-Much-Stock-Should-Worth/"
    data = asyncio.run(scrape_tradingview_comments(url))

    # 打印帖子作者
    author = data["post_author"]
    print(f"--- 帖子作者 ---")
    print(f"昵称: {author['username']}")
    print(f"主页: {author['profile_url']}\n")

    # 打印评论
    print(f"--- 帖子评论 ({len(data['comments'])}条) ---")
    for idx, c in enumerate(data["comments"]): # 仅打印前5条
        print(f"[{idx+1}] {c['username']} ({c['type']}): {c['content']} | {c['profile_url']}")
