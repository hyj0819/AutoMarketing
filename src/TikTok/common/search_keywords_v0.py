# tiktok_search_refined_v4.py
import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright
from time import sleep 

# ==================== 配置区域 ====================
MAX_SCROLLS = 10
STUCK_THRESHOLD = 3               
SCROLL_WAIT = (2.0, 3.5) 

# ==================== 修复后的提取函数 ====================
async def get_video_data(container, keyword):
    """
    基于用户提供的 grid-item-container 结构精准解析
    已增加对视频描述（Title/Desc）的提取
    """
    try:
        # 1. 定位作者信息
        author_a = await container.query_selector('a[data-e2e="search-card-user-link"]')

        # 2. 提取作者id和主页链接

        home_link = ""
        author_id = ""
        if author_a:
            href = await author_a.get_attribute('href')
            if href:
                home_link = f"https://www.tiktok.com{href}" if href.startswith('/') else href
                author_id = home_link.split('?')[0].split('/')[-1].replace('@', '')
        
        # 3. 提取视频链接
        video_a = await container.query_selector('a[href*="/video/"]')
        v_link = ""
        if video_a:
            v_link = await video_a.get_attribute('href')

        # 4. 【新增】提取视频标题/描述内容
        desc_elem = await container.query_selector('div[data-e2e="search-card-video-caption"]')
        video_title = ""
        if desc_elem:
            # 使用 inner_text 会自动合并所有 span 和 a 标签内的文字
            video_title = (await desc_elem.inner_text()).strip().replace('\n', ' ')

        # 5. 提取播放量/点赞数
        stats_elem = await container.query_selector('strong[data-e2e="video-views"]')
        views = 0
        if stats_elem:
            text = (await stats_elem.inner_text()).strip().upper()
            if 'K' in text: views = int(float(text.replace('K', '')) * 1000)
            elif 'M' in text: views = int(float(text.replace('M', '')) * 1000000)
            else: 
                try: views = int(text.replace(',', ''))
                except: views = 0

        # 6. 提取发布日期
        time_elem = await container.query_selector('div[class*="DivTimeTag"]')
        publish_time = (await time_elem.inner_text()).strip() if time_elem else ""

        return {
            "Keyword": keyword,
            "Author_ID": author_id,
            "Title": video_title,  # 新增字段
            "Author_Home": home_link,
            "Video_Link": v_link,
            "Stats": views,
            "Publish_Time": publish_time
        }
    except Exception as e:
        print(f"解析单个卡片出错: {e}")
        return None

# ==================== 核心逻辑 ====================
async def search_keywords(page, keyword):
    url = f"https://www.tiktok.com/search/video?q={keyword.replace(' ', '%20')}"
    print(f"🌐 正在检索关键词: {keyword}， 链接：{url}")
    
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(4) 

    captured_links = set()
    results = []
    consecutive_zero_count = 0 
    
    # 修正选择器：锁定包含视频和作者信息的大容器
    # 根据源码，它是包含 eh1ph437 类的 div
    ITEM_SELECTOR = 'div[class*="DivItemContainerV2"]'

    for i in range(MAX_SCROLLS):
        try:
            #print(f"⏳ 轮次 {i+1}: 等待元素加载...")
            await page.wait_for_selector(ITEM_SELECTOR, state="attached", timeout=10000)
        except Exception as e:
            print(f"⚠️ 轮次 {i+1}: 未检测到元素")
        
        # --- 核心改进：强制获取焦点并多手段滚动 ---
        # 1. 点击屏幕中心，确保滚动指令发送到主信息流
        #await page.mouse.click(640, 450) 

        """
        for _ in range(5): # 增加单次轮次的滚动次数
            # 2. 模拟鼠标滚轮
            await page.mouse.wheel(0, random.randint(1000, 1500))
            await asyncio.sleep(0.2)
            # 3. 辅助使用键盘 PageDown，这对 TikTok 非常有效
            await page.keyboard.press("PageDown")
            await asyncio.sleep(0.4)
        """
        
        # 4. 尝试寻找最后一个容器并强行滚动到它
        current_containers = await page.query_selector_all(ITEM_SELECTOR)
        if current_containers:
            try:
                await current_containers[-1].scroll_into_view_if_needed()
                await asyncio.sleep(random.randint(4, 7))
                #print(f"   📜 已强行滚动到第 {len(current_containers)} 个元素位置")
            except:
                pass
        
        await asyncio.sleep(3) # 给数据加载留出更多时间
        
        # 5. 增量解析
        new_count_in_round = 0
        for container in current_containers:
            data = await get_video_data(container, keyword)
            print(f'data:{data}')
            # 使用视频链接作为唯一标识去重
            if data and data["Video_Link"] and data["Video_Link"] not in captured_links:
                captured_links.add(data["Video_Link"])
                results.append(data)
                new_count_in_round += 1
                # print(f'成功抓取: {data["Author_ID"]} - {data["Video_Link"]}')
        
        print(f"   📥 轮次 {i+1}: 新增 {new_count_in_round} 条 | 总计 {len(results)} 条")

        # 6. 连续空跳退出逻辑
        if new_count_in_round == 0:
            consecutive_zero_count += 1
            if consecutive_zero_count >= STUCK_THRESHOLD:
                print(f"   🛑 连续 {STUCK_THRESHOLD} 次未发现新内容，停止滚动。")
                break
        else:
            consecutive_zero_count = 0 
            
    return results

# ==================== 启动程序 ====================
async def main():
    KEYWORDS = ["Indoor Golf"]
    OUTPUT_CSV = "tiktok_results_final.csv"
    HEADLESS = False  
    USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data" 
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=HEADLESS,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0]

        all_final_data = []
        for kw in KEYWORDS:
            try:
                data = await search_keywords(page, kw)
                all_final_data.extend(data)
                print(f"✅ '{kw}' 采集完成，当前累计 {len(all_final_data)} 条")
            except Exception as e:
                print(f"❌ 检索异常: {e}")
            await asyncio.sleep(random.randint(4, 7))

        if all_final_data:
            df = pd.DataFrame(all_final_data)
            df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            print(f"\n🎉 任务结束！共计 {len(df)} 条数据已导出至 {OUTPUT_CSV}")
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())