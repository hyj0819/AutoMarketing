import asyncio
from playwright.async_api import async_playwright
from src.utils.common_utils import get_text_response_ds 

USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"

async def scrape_xhs_comments(url):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url)
        await page.wait_for_timeout(3000)

        # 改用字典存储，以内容或用户 ID 为 Key 进行简单去重
        all_comments_data = {} 
        
        for i in range(50):
            # 1. 检查是否到底 (The End)
            is_end = await page.evaluate("""
                () => {
                    // 查找所有 div 和 span，因为 "THE END" 可能在这些标签中
                    const endTags = Array.from(document.querySelectorAll('div, span'));
                    return endTags.some(el => {
                        const text = el.innerText.toUpperCase(); // 统一转为大写处理
                        return text.includes('THE END') || 
                            text.includes('没有更多评论了') || 
                            text.includes('已显示全部评论');
                    });
                }
            """)
            if is_end:
                print(f"检测到 'The End'，共有 {len(all_comments_data)} 条评论，提前结束。")
                break

            # 2. 定位评论项
            items = await page.query_selector_all('div[id*="comment"], .comment-item, [data-testid="comment-item"]')
            
            current_round_count = 0
            for item in items:
                try:
                    # 过滤二级回复
                    is_reply = await item.evaluate("node => !!node.closest('.reply-container')")
                    if is_reply: continue

                    # 3. 提取用户名及主页链接
                    # 小红书的头像或昵称通常包裹在指向用户主页的 a 标签中
                    name_el = await item.query_selector('.nickname, .user-name, a.name')
                    content_el = await item.query_selector('.content, .comment-text, span.text')
                    
                    if name_el and content_el:
                        user_name = (await name_el.inner_text()).strip()
                        comment_text = (await content_el.inner_text()).strip()
                        
                        # 核心：获取主页链接 (a 标签的 href)
                        # 我们向上找最近的 a 标签，或者直接找 name_el 本身/父级
                        profile_link = await name_el.get_attribute('href')
                        if not profile_link:
                            # 备选方案：如果是嵌套在里面的 span，找它的父级 a
                            profile_link = await name_el.evaluate("el => el.closest('a') ? el.closest('a').href : ''")
                        
                        # 补全 URL (如果是相对路径)
                        if profile_link and profile_link.startswith('/'):
                            profile_link = f"https://www.xiaohongshu.com{profile_link}"

                        # 使用 (用户名+内容) 作为唯一键去重
                        unique_id = f"{user_name}_{comment_text}"
                        if unique_id not in all_comments_data:
                            all_comments_data[unique_id] = {
                                "user": user_name,
                                "profile_url": profile_link,
                                "text": comment_text
                            }
                            current_round_count += 1
                except:
                    continue

            print(f"轮次 {i+1}: 抓取新一级评论 {current_round_count} 条，总计 {len(all_comments_data)} 条")

            # 4. 滚动逻辑
            await page.evaluate("""
                () => {
                    const scrollable = Array.from(document.querySelectorAll('div'))
                        .find(el => (window.getComputedStyle(el).overflowY === 'auto' || window.getComputedStyle(el).overflowY === 'scroll') 
                                   && el.innerText.includes('评论'));
                    if (scrollable) scrollable.scrollTop += 1200;
                }
            """)
            await asyncio.sleep(4) # 优化性能，4-6秒通常足够加载 10 条

        # --- 转换为列表以便 AI 处理 ---
        final_list = list(all_comments_data.values())
        print(f"\n--- 爬取完成，开始 AI 判定 ---")

        # 5. AI 判定逻辑 (已根据你的变量名适配)
        potential_customers = []
        for c in final_list:
            # 这里的 prompt 针对 Lululemon 潜在客户
            prompt = f"分析以下评论内容: '{c['text']}'。此人是否表现出购买、求链接、询问价格或对 Lululemon 产品有浓厚兴趣？仅回答 'yes' 或 'no'。"
            system_msg = "你是一个获客专家。请简洁判断。"
            
            try:
                # 注意：确保 get_text_response_ds 已经 import
                ret = get_text_response_ds(prompt, system_msg).lower().strip()
                if 'yes' in ret:
                    print(f"🎯 潜在客户: {c['user']} | 链接: {c['profile_url']} | 内容: {c['text'][:20]}...")
                    potential_customers.append(c)
            except:
                continue

        await context.close()
        return potential_customers

target_url = "https://www.xiaohongshu.com/explore/69ba77a1000000001d01c66f?xsec_token=ABae1CREuACXYXUC8mdxkPACUE90dGApZhI6NyX5m1ZVI=&xsec_source=pc_user"

asyncio.run(scrape_xhs_comments(target_url))