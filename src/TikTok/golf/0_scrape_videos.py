import asyncio
import os, sys, json
import random
import time
import datetime
import csv

sys.path.append('src/TikTok/common')
from search_keywords_v0 import search_keywords
from scrape_reviews_v0 import scrape_comments, batch_scrape_comments  # ✅ 用新版
sys.path.append('src/utils')
from common_utils import get_text_response_ds, load_contacted_users

# ==================== 基础配置 ====================
PROJECT_NAME = "golf"
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_TK"
CONTACTED_USERS_FILE = f'files/TikTok/{PROJECT_NAME}/contacted_users.txt'
LOG_DIR = f"log/tiktok/{PROJECT_NAME}/{str(datetime.date.today())}"
TARGET_VIDEO_FILE = f"{LOG_DIR}/target_videos.txt"
TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
API_KEY_FILE = "conf/api_key.json"

USE_PERSONALIZED_MESSAGE = True
MAX_USERS = 5
EXCLUDE_AUTHOR = True

KEYWORDS = [
    "golf simulator",
    "indoor simulator",
    "launch monitor"
]

# golf 大V:
# https://www.tiktok.com/@golfsimrooms
# https://www.tiktok.com/@topgolf
# https://www.tiktok.com/@birdiesathleticclub

MESSAGES = []


async def main():
    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    all_potential_leads = []

    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)

    api_keys = json.load(open(API_KEY_FILE))
    if "deepseek" not in api_keys or "api_key" not in api_keys["deepseek"]:
        print(f"deepseek api key not found in {API_KEY_FILE}")
        exit(1)

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0]

        # --- 第一阶段：搜索视频 ---
        all_videos = []
        for kw in KEYWORDS:
            print(f"\n🔍 正在搜索关键词视频: {kw}")
            videos = await search_keywords(page, kw)
            all_videos.extend(videos)
            await asyncio.sleep(random.randint(1, 3))

        unique_videos = list({v['Video_Link']: v for v in all_videos if v['Video_Link']}.values())
        print(f"✅ 搜索完成，共获取 {len(unique_videos)} 个独立视频链接。")
        with open(TARGET_VIDEO_FILE, 'a') as fd:
            fd.writelines('\n'.join([x['Video_Link'] for x in unique_videos]))
            fd.writelines('\n')

        # --- 第二阶段：批量爬取评论（✅ 用 batch_scrape_comments，自动处理空评论区） ---
        video_urls = [v['Video_Link'] for v in unique_videos]
        video_meta = {v['Video_Link']: v for v in unique_videos}

        print(f"\n📦 开始批量爬取 {len(video_urls)} 个视频的评论...")
        all_comments_map = await batch_scrape_comments(context, video_urls)

        # --- 第三阶段：AI 筛选潜在客户 ---
        added_targets = []
        for v_url, comments in all_comments_map.items():
            v_title = video_meta[v_url].get('Title', '')
            v_author = video_meta[v_url].get('Author_ID', '')

            if not comments:
                print(f"⏭️ 跳过无评论视频: {v_url}")
                continue

            for c in comments:
                uid = c.get('uid')
                if (uid in contacted_users) or (uid in added_targets):
                    continue
                if EXCLUDE_AUTHOR and uid == v_author:
                    continue
                if not v_title.strip() or not c['text'].strip():
                    continue

                prompt = (
                    "【角色】\n"
                    "你是一位拥有 10 年经验的高尔夫行业资深市场分析师，擅长通过社交媒体的碎片化信息捕捉用户的购买信号（Buying Signals）。\n\n"
                    "【任务】\n"
                    "我将为你提供 TikTok 视频的【标题内容】和用户的【评论内容】。请你分析该用户是否有购买室内高尔夫模拟器的潜在意图。\n\n"
                    "【判定维度】\n"
                    "请基于以下几个维度进行判断（判断标准需要严格一些，得要有比较明确的购买信号）：\n"
                    "1、用户是否在咨询购买意见/寻求推荐。\n"
                    "2、用户是否在抱怨现有设备的问题，或表达了具体的环境限制（如天气、空间）。\n"
                    "3、用户是否询问了关于价格、品牌、参数、安装或软件兼容性的问题。\n"
                    "4、用户是否提到了自己的家庭环境（如车库、地下室、办公室）。\n"
                    "5、用户是否表达了强烈的羡慕或“我也想要一套”的愿望。\n\n"
                    "【输出格式】\n"
                    "请直接输出yes或者no，不需要其他说明。\n\n"
                    f"【标题内容】: {v_title}\n\n"
                    f"【评论内容】: {c['text']}"
                )
                is_potential = get_text_response_ds(
                    "你是一个获客专家。请简洁判断。", prompt,
                    api_key=api_keys["deepseek"]["api_key"]
                )

                if is_potential.lower() == 'yes':
                    all_potential_leads.append({
                        "User_ID": uid,
                        "User_Page": c.get('upage'),
                        "Comment": c['text'],
                        "Source_Video": v_url,
                        "Source_Title": v_title
                    })
                    added_targets.append(uid)
                    print(f"🎯 发现目标用户: {uid}")

        # 去重
        all_potential_leads = list({u['User_ID']: u for u in all_potential_leads}.values())

        # --- 第四阶段：生成个性化文案并保存 ---
        print(f"\n🚀 开始生成文案，目标用户数: {len(all_potential_leads)}")
        potential_customer_data = [['uid', 'source url', 'source title', 'source comment', 'message']]

        for idx, lead in enumerate(all_potential_leads):
            target_id = lead["User_ID"]

            if USE_PERSONALIZED_MESSAGE:
                prompt = (
                    "【角色】\n"
                    "你是一位资深的高尔夫行业海外营销专家，擅长通过社交媒体（TikTok/Instagram/Reddit）进行精准截流获客。你的话术风格：专业、像圈内朋友、乐于助人、不生硬推销。\n\n"
                    "【背景】\n"
                    "我司经营高端室内高尔夫模拟器（Indoor Golf Simulator）。\n"
                    "产品核心优势：\n"
                    "1. 内置120+全国知名球场，1:1真实还原球场原貌。\n"
                    "2. 通过高清摄像头对球体和杆头进行动态实时捕捉，获得专业、精准的运动数据。\n"
                    "3. 以空气动力学算法为支撑，AI机器学习海量场外数据，实现运动轨迹智能精准预判。\n"
                    "4. 集成先进的physx物理引擎，高度模拟天气、风速、海拔等环境因素。\n"
                    "5. 内置智能电子球童，提供球场信息提示、线路辅助决策、障碍难点分析。\n\n"
                    "目标：根据用户评论生成个性化英文私信，吸引对方关注产品并建立联系。\n\n"
                    "【写作准则】\n"
                    "- 开场白：先用半句话带出原帖核心内容，再衔接用户评论，证明你真的读懂了。\n"
                    "- 禁止直接说“买我们的机器”，要用“我这里有解决方案/实拍视频，你想看看吗？”的方式。\n"
                    "- 每次选1-2个与评论场景最相关的产品优势自然嵌入，不要罗列全部卖点。\n"
                    "- 长度：严格控制在3-4句话，总字符数不超过350个。\n"
                    "- 语言：英文。整个私信前后不用加双引号。\n\n"
                    f"【帖子内容】：{lead['Source_Title']}\n\n"
                    f"【评论内容】：{lead['Comment']}"
                )
                message = get_text_response_ds("", prompt, api_key=api_keys["deepseek"]["api_key"])
            else:
                message = random.choice(MESSAGES)

            print(f"({idx+1}/{len(all_potential_leads)}) {target_id}")
            print(f'📚 原贴: {lead["Source_Title"]}')
            print(f'💬 评论: {lead["Comment"]}')
            print(f'📝 文案: {message}\n')

            if message:
                potential_customer_data.append([
                    target_id,
                    lead['Source_Video'],
                    lead['Source_Title'],
                    lead['Comment'],
                    message
                ])

        with open(TARGET_USERS_FILE, 'w', newline='', encoding='utf-8') as file:
            csv.writer(file).writerows(potential_customer_data)

        print(f"\n💾 任务结束。潜在客户数据已保存至 {TARGET_USERS_FILE}")
        await context.close()


if __name__ == "__main__":
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    start = time.time()
    asyncio.run(main())
    end = time.time()
    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    duration = end - start
    print(f"⏱️ 运行时长: {int(duration//3600):02d}:{int((duration%3600)//60):02d}:{duration%60:06.3f}")