import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright

# ==================== 配置区域 ====================
MAX_SCROLLS = 20
STUCK_THRESHOLD = 3               
SCROLL_WAIT = (3.0, 5.0) 
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"

# ==================== 提取函数 ====================
async def get_post_data(container, subreddit_name):
    """
    基于 Reddit 的 shreddit-post 结构解析帖子信息
    """
    try:
        # 1. 提取作者和 ID
        # Reddit 的帖子组件通常直接带有 author 属性
        author = await container.get_attribute('author') or "[deleted]"
        post_id = await container.get_attribute('id')
        
        # 2. 提取帖子标题
        # 标题通常在 post-title 属性或内部的 h1/faceplate-screen-reader-content 中
        post_title = await container.get_attribute('post-title')
        if not post_title:
            title_elem = container.locator('a[slot="full-post-link"]')
            post_title = await title_elem.inner_text() if await title_elem.count() > 0 else ""

        # 3. 提取帖子详情页链接 (修正版)
        # permalink 属性包含的是相对路径，例如 /r/Golfsimulator/comments/1t6zzzz/...
        permalink = await container.get_attribute('permalink')
        if permalink:
            post_link = f"https://www.reddit.com{permalink}"
        else:
            # 备选方案：如果 permalink 不存在，再尝试 content-href
            post_link = await container.get_attribute('content-href') or ""
        # 4. 提取互动数据 (点赞数)
        score = await container.get_attribute('score') or "0"
        
        # 5. 提取评论数
        comment_count = await container.get_attribute('comment-count') or "0"

        # 6. 提取发布时间
        # 通常在 created-timestamp 属性中
        created_time = await container.get_attribute('created-timestamp') or ""

        return {
            "Subreddit": subreddit_name,
            "Post_ID": post_id,
            "Author": author,
            "Title": post_title.strip(),
            "Link": post_link,
            "Score": int(score),
            "Comment_Count": int(comment_count),
            "Publish_Time": created_time,
            "Author_Home": f"https://www.reddit.com/user/{author}"
        }
    except Exception as e:
        # print(f"解析单个帖子出错: {e}")
        return None

# ==================== 核心逻辑 ====================
async def scrape_subreddit(page, subreddit_url):
    print(f"🌐 正在访问节点: {subreddit_url}")
    
    await page.goto(subreddit_url, wait_until="domcontentloaded")
    await asyncio.sleep(4) 

    captured_ids = set()
    results = []
    consecutive_zero_count = 0 
    
    # Reddit 帖子的核心组件选择器
    POST_SELECTOR = 'shreddit-post'

    for i in range(MAX_SCROLLS):
        # 1. 滚动到底部触发加载
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        wait_time = random.uniform(*SCROLL_WAIT)
        await asyncio.sleep(wait_time)
        
        # 2. 获取当前页面所有帖子组件
        current_containers = await page.locator(POST_SELECTOR).all()
        
        # 3. 增量解析
        new_count_in_round = 0
        subreddit_name = subreddit_url.split('/r/')[-1].split('/')[0]
        
        for container in current_containers:
            data = await get_post_data(container, subreddit_name)
            
            # 使用 Post_ID 作为唯一标识去重
            if data and data["Post_ID"] and data["Post_ID"] not in captured_ids:
                if data["Comment_Count"] > 0:
                    captured_ids.add(data["Post_ID"])
                    results.append(data)
                new_count_in_round += 1
        
        print(f"   📥 轮次 {i+1}: 滚动后新增 {new_count_in_round} 条 | 总计 {len(results)} 条")

        # 4. 连续空跳退出逻辑
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
    # 可以放多个节点链接
    TARGET_SUBREDDITS = [
        "https://www.reddit.com/r/Golfsimulator/hot/"
    ]
    OUTPUT_CSV = "reddit_posts_results.csv"
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0]

        all_final_data = []
        for url in TARGET_SUBREDDITS:
            try:
                data = await scrape_subreddit(page, url)
                all_final_data.extend(data)
            except Exception as e:
                print(f"❌ 采集异常: {e}")
            await asyncio.sleep(random.randint(3, 5))

        if all_final_data:
            df = pd.DataFrame(all_final_data)
            # 按照点赞数降序排列
            #df = df.sort_values(by="Score", ascending=False)
            df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            print(f"\n🎉 任务结束！共计 {len(df)} 条帖子数据已导出至 {OUTPUT_CSV}")
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())