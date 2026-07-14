import asyncio
import os, sys
import random
import time
import datetime
import pandas as pd
from time import sleep
import csv, requests
import json

# 导入 Reddit 专用模块
from scrape_articles_v0 import scrape_subreddit
from scrape_reviews_v0 import scrape_reddit_comments
from chat_v0 import send_reddit_dm
sys.path.append('src/utils')
from common_utils import get_text_response_ds, load_contacted_users, get_adspower_ws


USE_PERSONALIZED_MESSAGE = True
MAX_USERS = 20
EXCLUDE_AUTHOR = True
POST_IS_PRIOR_TO_COMMENT = True

# 话术库
MESSAGES = [
    "I see you’re looking for stock ideas and setups in the comments. You want something actionable, right?",
    "What you’ve been looking for, I can actually get for you.",
    "Must be tiring waiting in comments all the time. Let me help you out.",
    "I have some stock ideas from our creator that I can send you.",
    "I can send you some stock ideas."
]
MESSAGES = [
    "I saw your comment about the golf simulator. Are you looking for a home setup?",
    "Hey! I have some great indoor golf ideas if you're interested.",
    "Nice comment on that golf post. I actually work with these setups, want to chat?"
]


def is_target_user(is_post, post_content, comment_content='', api_key=""):
    # AI 意图判定 (参考 scrape_reviews_v0 逻辑)
    prompt = "【角色】\n"\
            "你是一位拥有 10 年经验的高尔夫行业资深市场分析师，擅长通过社交媒体的碎片化信息捕捉用户的购买信号（Buying Signals）。\n\n"\
            "【任务】\n"\
            f"我将为你提供 Reddit 帖子的【正文内容】{'和用户的【评论内容】' if not is_post else ''}。请你分析该用户是否有购买室内高尔夫模拟器的潜在意图。\n\n"\
            "【判定维度】\n"\
            "请基于以下几个维度进行判断（判断标准需要严格一些，得要有比较明确的购买信号）：\n"\
            "1、用户是否在咨询购买意见/寻求推荐。\n"\
            "2、用户是否在抱怨现有设备的问题，或表达了具体的环境限制（如天气、空间）。\n"\
            "3、用户是否询问了关于价格、品牌、参数、安装或软件兼容性的问题。\n"\
            "4、用户是否提到了自己的家庭环境（如车库、地下室、办公室）。\n"\
            "5、用户是否表达了强烈的羡慕或“我也想要一套”的愿望。\n\n"\
            "【输出格式】\n"\
            "请直接输出yes或者no，不需要其他说明。\n\n"\
            f"【正文内容】: {post_content}\n\n"\
            f"{f'【评论内容】: {comment_content}' if not is_post else ''}"
    is_potential = get_text_response_ds("你是一个获客专家。请简洁判断。", prompt, api_key=api_key)

    return is_potential


async def main():
    # ==================== 基础配置 ====================
    PROJECT_NAME = "golf"
    FLAG = "new"
    USER_DATA_DIR = "/Users/hyj/Documents/mywork/AutoMarketing/chrome_data/Chrome_Bot_Data_TK"
    CONTACTED_USERS_FILE = f'files/Reddit/{PROJECT_NAME}/contacted_users.txt'
    LOG_DIR = f"log/reddit/{PROJECT_NAME}/{str(datetime.date.today())}/{FLAG}"
    TARGET_POST_FILE = f"{LOG_DIR}/target_posts.txt"
    TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
    API_KEY_FILE = "conf/api_key.json"

    # 目标 Subreddit 列表
    TARGET_SUBREDDITS = [
        f"https://www.reddit.com/r/Golfsimulator/{FLAG}/"
    ]

    USE_CHROME = False
    ADSPOWER_USER_ID = "k1byap97"  # "k1byab0k", "k1byap97"
    ACCOUNT_NAME = "StockPulseTrader" # "NEAGLE_GOLF", "StockPulseTrader"

    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'使用账号:{ACCOUNT_NAME}')
    if USE_CHROME:
        print('使用Chrome浏览器')
    else:
        print(f'指纹浏览器USER_ID:{ADSPOWER_USER_ID}\n')

    # 1. 初始化
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
            ws_endpoint = get_adspower_ws(ADSPOWER_USER_ID)
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0]

        page = context.pages[0]
        #sleep(3000)
        # --- 第一阶段：搜索视频 ---
        all_posts = []
        for sub in TARGET_SUBREDDITS:
            print(f"\n🕷 正在处理子节点: {sub}")
            posts = await scrape_subreddit(page, sub)
            all_posts.extend(posts)
            await asyncio.sleep(random.randint(1, 3))

        # 视频去重
        unique_posts = {v['Link']: v for v in all_posts if v['Link']}.values()
        print(f"✅ 搜索完成，共获取 {len(unique_posts)} 个独立视频链接。")
        with open(TARGET_POST_FILE, 'a') as fd:
            fd.writelines('\n'.join([x['Link'] for x in unique_posts]))
            fd.writelines('\n')

        # --- 第二阶段：爬取评论并筛选潜在客户 ---
        print("\n\n🕷 开始提取评论")
        potential_users_in_post = []
        added_targets = []
        for v_idx, post in enumerate(unique_posts):
            v_url = post['Link']
            v_title = post['Title']
            v_author = post['Author']
            v_author_url = post['Author_Home']
            print(f"\n({v_idx+1}/{len(unique_posts)})")
            print(f"📊 正在爬取文章评论: {v_url}")
            
            try:
                # 调用 scrape_reviews_v0 的逻辑 (注意：内部需处理浏览器切换或直接传入page)
                # 假设针对单个视频爬取
                comments = await scrape_reddit_comments(page, v_url)
                post_content = comments[0]['post_content']

                if v_author in added_targets or v_author in contacted_users: continue

                if post_content.strip() == "": continue

                is_potential = is_target_user(is_post=True, post_content=post_content, api_key=api_keys["deepseek"]["api_key"])
                if is_potential.lower() == 'yes':
                    all_potential_leads.append({
                        "User_ID": v_author,
                        "User_Page": v_author_url,
                        "Comment": '',
                        "Source_Post": v_url,
                        "Source_Title": v_title,
                        "Souce_Content": post_content,
                        'is_post': True
                    })
                    print(f"🎯 从正文发现目标用户: {v_author}")

                    added_targets.append(v_author)

                    if POST_IS_PRIOR_TO_COMMENT:
                        potential_users_in_post.append(v_author)

                for c in comments:
                    uid = c.get('comment_author')
                    comment_content = c['comment_content']

                    # 过滤已联系用户
                    if (uid in contacted_users) or (uid in added_targets) or (EXCLUDE_AUTHOR and uid == v_author): continue

                    if post_content.strip() == "" or comment_content.strip() == "": continue
                    
                    if POST_IS_PRIOR_TO_COMMENT and uid in potential_users_in_post: continue

                    # AI 意图判定 (参考 scrape_reviews_v0 逻辑)

                    is_potential = is_target_user(is_post=False, post_content=post_content, comment_content=comment_content, api_key=api_keys["deepseek"]["api_key"])
                    
                    print(f'❓ 评论内容：{comment_content}, is_potential:{is_potential}')

                    if is_potential.lower() == 'yes':
                        all_potential_leads.append({
                            "User_ID": uid,
                            "User_Page": c.get('profile_url'),
                            "Comment": comment_content,
                            "Source_Post": v_url,
                            "Source_Title": v_title,
                            "Souce_Content": post_content,
                            'is_post': False
                        })
                        print(f"🎯 从评论区发现目标用户: {uid}")

                        added_targets.append(uid)
            except Exception as e:
                print(f"  ❌ 爬取评论出错: {e}")
            finally:
                await asyncio.sleep(random.randint(30, 80))

        # 用户去重
        all_potential_leads = {u['User_ID']: u for u in all_potential_leads}.values()

        # --- 第三阶段：私信触达 ---
        print(f"\n🚀 开始执行私信任务，目标总数: {len(all_potential_leads)}")

        """
        with open(TARGET_USERS_FILE, 'a') as fd:
            fd.writelines('\n'.join([x['User_ID'] for x in all_potential_leads]))
            fd.writelines('\n')
        """

        sent_this_round = []
        success_cnt = 0
        potential_customer_data = []
        for idx, lead in enumerate(all_potential_leads):
            target_id = lead["User_ID"]

            if USE_PERSONALIZED_MESSAGE:
                prompt = "【角色】\n"\
                    "你是一位资深的高尔夫行业海外营销专家，擅长通过社交媒体（TikTok/Instagram/Reddit）进行精准截流获客。你的话术风格：专业、像圈内朋友、乐于助人、不生硬推销。\n"\
                    "\n"\
                    "【背景】\n"\
                    "我司经营高端室内高尔夫模拟器（Indoor Golf Simulator）。\n"\
                    "产品核心优势：\n"\
                    "1. 内置120+全国知名球场，1:1真实还原球场原貌，细致刻画到每一颗花草、树木和水流、蓝天等。\n"\
                    "2. 通过高清摄像头对球体和杆头进行动态实时捕捉，获得专业、精准的运动数据。\n"\
                    "3. 以空气动力学算法为支撑，通过自主模型解算，AI机器学习海量场外数据，实现运动轨迹智能精准预判。\n"\
                    "4. 集成先进的physx物理引擎，在弹跳、反弹、滚动等物理效果上具有逼真的虚拟效果，同时高度模拟环境对运动数据的影响，包括天气、风速、海拔等因素对击球轨迹的修正。\n"\
                    "5. 内置智能电子球童功能，提供球场信息提示、线路辅助决策、障碍难点分析。\n"\
                    "6. 创新小程序控制交互功能，通过小程序实现球场切换等。\n"\
                    "7. 内置下场规则，包括比杆、比洞、四人四球、四人两球等。\n"\
                    "8. 多人PK模式，支持四人拉斯、斗地主、打老虎等PK游戏。\n"\
                    "\n"\
                    f"目标：根据用户在一段社交媒体{'内容下的评论' if not lead['is_post'] else '发布的帖子'}，生成一段英文私信，吸引对方关注我们的产品并建立联系。\n"\
                    "\n"\
                    f"任务：我将为你提供【帖子内容】{'和【评论内容】' if not lead['is_post'] else ''}。请根据这两个信息，生成一段个性化的英文私信。\n"\
                    "\n"\
                    "【写作准则】\n"\
                    "\n"\
                    "开场白（必选，结构分两步）：\n"\
                    "第一步——记忆钩子：先用半句话带出原帖的核心内容或主题，帮用户回忆起当时在说什么。例如原帖是”在家打球不用真的球！“，可以写成“Saw your comment on that 'no ball needed' home setup post…”。禁止直接说“我注意到你帖子/评论了…”，要自然得像刚好刷到同一个帖子的球友。\n"\
                    f"第二步——衔接{'评论' if not lead['is_post'] else '帖子内容'}：紧接着用你自己的话把{'用户的评论和原帖' if not lead['is_post'] else '原帖'}的关联讲清楚，证明你真的读懂了。例如用户的内容是”😂😂😂“，你可以说“你的笑哭表情太真实了，第一眼看确实觉得离谱但细想又有点心动“。\n"\
                    "\n"\
                    "禁止的做法：\n"\
                    "- 只孤立地引用原贴或评论中的单词（如”'Winter'—great answer!“）\n"\
                    "- 以”Dear“或”I noticed you commented on…“开头\n"\
                    "- 禁止直接生搬硬套上述样例中的词，要结合原内容和评论来生成。\n"\
                    "\n"\
                    "隐形推销：\n"\
                    "- 禁止直接说”买我们的机器“\n"\
                    "- 要说”我这里正好有解决这个问题的视频/方案/数据，你想看看吗？“或”如果你好奇这类装备实际效果，我可以发段实拍给你“\n"\
                    "- 不涉及与竞品的技术对比，只介绍自家产品的相关优势\n"\
                    "- 每次选1-2个与帖子/评论场景最相关的产品优势自然嵌入，不要罗列全部卖点\n"\
                    "\n"\
                    "长度：严格控制在3-4句话，总字符数（含空格和标点）不超过350个。\n"\
                    "\n"\
                    "语气：专业但亲切，像一个乐于分享好装备的圈内球友，不生硬推销。\n"\
                    "\n"\
                    "语言：英文。\n"\
                    "\n"\
                    "其他： 若无必须，整个私信的前后不用加双引号\n"\
                    "\n"\
                    f"【帖子内容】：{lead['Souce_Content']}\n\n"\
                    f"""{f"【评论内容】：{lead['Comment']}" if not lead['is_post'] else ""}"""
                message = get_text_response_ds("", prompt, api_key=api_keys["deepseek"]["api_key"])
            else:
                message = random.choice(MESSAGES)
            
            print(f"({idx+1}/{len(all_potential_leads)})")
            #print(f"📩 正在和 {target_id} 建联...")
            print(f'📚 原贴内容:{lead["Souce_Content"]}\n')
            print(f'📝 评论内容:{lead["Comment"]}\n')
            print(f'📝 is_post:{lead["is_post"]}\n')
            print(f'📝 文案内容: {message}\n\n')
            
            if message == '':
                continue

            potential_customer_data.append([
                target_id, lead['Source_Post'], lead['Souce_Content'], lead['Comment'], message
            ])


            """
            try:
                # 调用 chat_v0 的发送函数
                # 注意：send_direct_message 内部逻辑需适配 TikTok
                success = await send_reddit_dm(page, target_id, message)
                
                if success:
                    sent_this_round.append(target_id)
                    contacted_users.add(target_id)
                    # 严格冷却防止封号
                    await asyncio.sleep(random.randint(60, 150))

                    success_cnt += 1

                    if success_cnt > MAX_USERS:
                        break

            except Exception as e:
                print(f"  ❌ 私信失败: {e}")


        if sent_this_round:
            with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
                for user in sent_this_round:
                    f.write(f"{user}\n")
        
        print(f"\n💾 任务结束。本轮成功发送 {len(sent_this_round)} 条私信。")
        """

        # 写入文件
        with open(TARGET_USERS_FILE, 'w', newline='', encoding='utf-8') as file:
            potential_customer_data.insert(0, ['uid', 'source url', 'source content', 'source comment', 'message'])
            writer = csv.writer(file)
            writer.writerows(potential_customer_data)

        print("\n💾 任务结束。潜在客户数据已保存！")

        await context.close()

if __name__ == "__main__":
    start = time.time()
    asyncio.run(main())
    end = time.time()

    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    duration = end - start
    hours = int(duration // 3600)
    minutes = int((duration % 3600) // 60)
    seconds = duration % 60
    print(f"⏱️ 运行时长: {hours:02d}:{minutes:02d}:{seconds:06.3f}")
