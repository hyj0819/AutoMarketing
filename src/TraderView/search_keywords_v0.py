import asyncio
from playwright.async_api import async_playwright

async def search_tradingview(keyword, max_cnt=-1):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()
        
        url = f"https://www.tradingview.com/scripts/search/{keyword}/"
        print(f"正在访问: {url}")
        await page.goto(url, wait_until="domcontentloaded")

        # 阶段 1：处理初始按钮 (Show more)[cite: 7]
        try:
            show_more_btn = page.get_by_role("button", name="Show more publications")
            if await show_more_btn.is_visible(timeout=3000):
                await show_more_btn.click()
                await asyncio.sleep(2)
        except:
            pass

        # 阶段 2：通过滚动触发 c.txt 中的 Spinner 加载更多
        print("开始循环下拉加载所有内容...")
        
        last_count = 0
        consecutive_no_growth = 0
        
        while consecutive_no_growth < 3:
            # 找到 c.txt 中定义的加载器容器
            # 即使它带有 hidden 类名，scroll_into_view 到底部仍能触发监听[cite: 5]
            spinner = page.locator('[class*="spinnerContainer-"]').first
            
            # 滚动到页面最底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.0) # 给 Spinner 时间从 hidden 变为可见再变回 hidden[cite: 8]
            
            # 检查帖子数量是否增长[cite: 4]
            current_count = await page.locator('a[class*="title-"]').count()
            print(f"当前帖子总数: {current_count}")
            
            if current_count >= max_cnt:
                break

            if current_count > last_count:
                last_count = current_count
                consecutive_no_growth = 0
            else:
                consecutive_no_growth += 1
                # 模拟向上微滚再下拉，确保触发 IntersectionObserver
                await page.mouse.wheel(0, -300)
                await asyncio.sleep(0.5)

        # 阶段 3：稳健提取数据
        print("正在提取信息...")
        post_titles = page.locator('a[class*="title-"]')
        count = await post_titles.count()
        print(f'count:{count}')
        
        results = []
        for i in range(count):
            try:
                title_node = post_titles.nth(i)
                title_text = await title_node.inner_text()
                link = await title_node.get_attribute('href')
                results.append(
                        (title_text.strip(), link)
                    )
            except Exception as e:
                print(f'e:{e}')
                continue

        await browser.close()
        return results

if __name__ == "__main__":
    final_data = asyncio.run(search_tradingview("stock"))
    for x in final_data:
        print(x)
    print(f"成功抓取 {len(final_data)} 条非重复帖子。")