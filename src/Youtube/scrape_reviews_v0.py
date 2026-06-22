import asyncio
import re
from playwright.async_api import async_playwright
from time import sleep 

async def scrape_youtube_shorts_comments(url):
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=False) # 建议先设为 False 观察过程
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"🚀 正在访问: {url}")
        await page.goto(url)
        
        sleep(30000000)
        #exit(0)
        # --- 步骤 1: 点击评论按钮 ---
        try:
            # 使用正则表达式匹配 aria-label 中包含 "comment" 的按钮
            comment_btn = page.locator('button[aria-label*="comment" i]')
            await comment_btn.wait_for(state="visible", timeout=15000)
            # 使用 force=True 防止被其他隐藏层拦截
            await comment_btn.click(force=True)
            print("✅ 评论按钮已点击")
        except Exception as e:
            print(f"❌ 无法点击评论按钮: {e}")
            await page.screenshot(path="error_click.png")
            await browser.close()
            return

        # --- 步骤 2: 等待评论面板出现 ---
        # Shorts 的评论面板通常是一个 visible 的 engagement-panel
        panel_selector = "ytd-engagement-panel-section-list-renderer:visible"
        try:
            await page.wait_for_selector(panel_selector, state="visible", timeout=15000)
            print("✅ 评论面板已展开")
        except:
            print("⚠️ 未探测到标准面板，尝试寻找通用评论容器...")
            panel_selector = "#comments"

        # --- 步骤 3: 循环滚动加载评论 ---
        print("⏳ 正在加载所有评论，请稍候...")
        
        last_comment_count = 0
        consecutive_no_change = 0
        
        while True:
            # 获取当前所有评论节点
            comments = page.locator("ytd-comment-thread-renderer")
            count = await comments.count()
            
            if count > 0:
                # 滚动到最后一个评论，触发懒加载
                await comments.last.scroll_into_view_if_needed()
                # 稍微向上滚一点点再向下，有时能更稳地触发加载
                await page.mouse.wheel(0, 500)
            
            await asyncio.sleep(2) # 等待网络请求
            
            if count == last_comment_count:
                consecutive_no_change += 1
            else:
                consecutive_no_change = 0
                last_comment_count = count
                print(f"已加载 {count} 条评论...")

            # 如果连续 3 次滚动数量没变化，认为加载完毕
            if consecutive_no_change >= 3:
                break

        # --- 步骤 4: 提取数据（针对 ytd-comment-view-model 结构） ---
        print("📊 正在解析数据...")
        all_comments = []

        # 获取所有评论线程容器
        comment_nodes = await page.query_selector_all("ytd-comment-thread-renderer")

        for node in comment_nodes:
            try:
                # 1. 提取作者
                # 新版 YouTube 常用 #author-text 或 a#author-text
                author_el = await node.query_selector("#author-text")
                author = await author_el.inner_text() if author_el else "Unknown"

                # 2. 提取评论内容
                content_el = await node.query_selector("#content-text")
                content = await content_el.inner_text() if content_el else ""

                # 3. 提取时间 (针对你提供的 HTML 源码)
                # 直接定位 id 为 published-time-text 的元素
                time_el = await node.query_selector("#published-time-text")
                if time_el:
                    time_text = await time_el.inner_text()
                else:
                    # 备选方案：如果 ID 找不到，寻找包含 "ago" 字样的链接
                    time_el = await node.query_selector("a[href*='&lc=']")
                    time_text = await time_el.inner_text() if time_el else "Unknown"

                if content:
                    all_comments.append({
                        "author": author.strip(),
                        "text": content.strip(),
                        "time": time_text.strip()
                    })
                    
            except Exception as e:
                print(f'exception:{e}')
                # 即使某一条解析失败，也继续下一条
                continue

        # --- 步骤 5: 结果输出 ---
        print(f"\n🎉 抓取结束！总计找到 {len(all_comments)} 条评论。")
        for idx, item in enumerate(all_comments[:10]): # 打印前10条
            print(f"{idx+1}. [{item['author']}] ({item['time']}): {item['text'][:50]}...")

        await browser.close()
        return all_comments

# 执行
if __name__ == "__main__":
    target_url = "https://www.youtube.com/shorts/DRvJLb8kLvY"
    asyncio.run(scrape_youtube_shorts_comments(target_url))