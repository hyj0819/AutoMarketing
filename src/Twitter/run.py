import asyncio
import csv, json
import sys
import random
import time
import datetime
from time import sleep

sys.path.append('src/utils')
from search_keywords_v0 import scrape_keyword, parse_args as search_args, deduplicate
from scrape_reviews_v0 import scrape_x_comments
#from chat_v0 import auto_send_dm
from common_utils import get_text_response_ds, load_contacted_users, get_adspower_ws

# 基础配置
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_1"
PROJECT_NAME = "golf"
FLAG = 'new'
CONTACTED_USERS_FILE = f'files/Twitter/{PROJECT_NAME}/contacted_users.txt'
#MAX_POSTS_PER_KEYWORD = 10000  # 每个关键词处理多少个帖子
LATEST_HOURS = 216000  # 抓取近N小时的帖子
SEAECH_BY_LATEST = False
MAX_POST = 100000
USE_PERSONALIZED_MESSAGE = True
LOG_DIR = f"log/twitter/{PROJECT_NAME}/{str(datetime.date.today())}/{FLAG}"
TARGET_POST_FILE = f"{LOG_DIR}/target_posts.txt"
TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
API_KEY_FILE = "conf/api_key.json"

USE_CHROME = False
ADSPOWER_USER_ID = "k1byap97"  #"k1byab0k"、 "k1byap97"
ACCOUNT_NAME = "StockPulseTrader"   #"Cassian"、 "Coast Cao"

KEYWORDS = [
    "golf simulator"
]


MESSAGES = [
    "I saw your comment about the golf simulator. Are you looking for a home setup?",
    "Hey! I have some great indoor golf ideas if you're interested.",
    "Nice comment on that golf post. I actually work with these setups, want to chat?"
]


def is_target_user(is_post, post_content, comment_content='', api_key=''):
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
    # 1. 初始化
    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    sent_this_round = []
    
    # 获取搜索参数
    args = search_args()
    args.hours = LATEST_HOURS
    args.search_by_latest = SEAECH_BY_LATEST
    args.max_post = MAX_POST
    args.max_idle_scrolls =10000

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

        page = await context.new_page()

        # --- 第一阶段：搜索帖子
        all_posts = []
        for kw in KEYWORDS:
            args.keywords = kw
            if FLAG == 'new':
                args.search_by_latest = True
            print(f"🔍 正在搜索关键词: {kw}")
            print(f'Search args:{args}')

            start = time.time()

            posts = await scrape_keyword(page, args)

            end = time.time()
            get_dur(start, end, f'搜索{kw}相关帖子')

            all_posts.extend(posts)
        
        #print(f"🕷 共爬取到{len(all_posts)}个帖子:{[x['text'] for x in all_posts]}")

        target_posts = deduplicate(all_posts)

        print(f"✅ 筛选出 {len(target_posts)} 个待分析帖子：{target_posts}")
        with open(TARGET_POST_FILE, 'a') as fd:
            fd.writelines('\n'.join([x['url'] for x in target_posts]))
            fd.writelines('\n')

        # --- 第二阶段：抓取评论并筛选用户
        start = time.time()
        potential_leads = {}
        added_targets = []
        for post_idx, post in enumerate(target_posts):
            post_url = post['url']
            author = post['author']
            author_url = f"https://x.com/{author.replace('@', '')}"
            post_ts = int(datetime.datetime.strptime(post['publishedAt'], "%Y-%m-%dT%H:%M:%S.%fZ").timestamp())

            print(f"({post_idx+1}/{len(target_posts)})")
            print(f"📑 正在分析帖子: {post_url}")

            post_text = post['text']

            if author in added_targets: continue
            
            if post_text.strip() == "": continue

            is_target = is_target_user(is_post=True, post_content=post_text, api_key=api_keys["deepseek"]["api_key"])

            if is_target.lower() == 'yes':
                if (author, author_url) in potential_leads:
                    (latest_ts, _, _, _, _) = potential_leads.get((author, author_url))
                    if latest_ts < post_ts:
                        potential_leads[(author, author_url)] = (post_ts, "", post_text, post_url, True) # publish_ts, comment, post_text, is_post
                else:
                    potential_leads[(author, author_url)] = (post_ts, "", post_text, post_url, True)
                    added_targets.append(author)

                print(f"🎯 从帖子正文发现目标用户: {author}")

            # 调用 scrape_x 逻辑提取评论
            # 注意：需将原 scrape_x.py 中的逻辑封装进一个可调用的函数
            comments = await scrape_x_comments(page, post_url, LOG_DIR)
            
            for comment in comments:
                username = comment['uid'] # 例如 @user123
                profile_url = comment['upage']
                comment_text = comment['text']
                comment_ts = int(datetime.datetime.strptime(comment['timestamp'], "%Y-%m-%dT%H:%M:%S.%fZ").timestamp())

                if post_text.strip() == "" or comment_text.strip() == "": continue

                # 排除已联系过的用户[cite: 6]
                if username in contacted_users or username in added_targets: continue

                is_target = is_target_user(is_post=False, post_content=post_text, comment_content=comment_text, api_key=api_keys["deepseek"]["api_key"])

                print(f'❓ 评论内容：{comment_text}, is_potential:{is_target}')

                # 保留同一个用户的最新评论
                if is_target.lower() == 'yes':
                    if (username, profile_url) in potential_leads:
                        (latest_ts, _, _, _, _) = potential_leads.get((username, profile_url))
                        if latest_ts < comment_ts:
                            potential_leads[(username, profile_url)] = (comment_ts, comment_text, post_text, post_url, False)
                    else:
                        potential_leads[(username, profile_url)] = (comment_ts, comment_text, post_text, post_url, False)
                        added_targets.append(username)
                    
                    print(f"🎯 从评论区发现目标用户: {username}")

                print('\n\n')
        
        await context.close()

        end = time.time()
        get_dur(start, end, '分析帖子')

        # --- 第三阶段：执行私信触达 ---
        print(f"🎯 找到 {len(potential_leads)} 个目标用户，准备建联...")

        start = time.time()
        potential_customer_data = []
        for lead_idx, ((username, profile_url), (comment_ts, comment_text, post_text, post_url, is_post)) in enumerate(potential_leads.items()):
            if username in contacted_users: continue

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
                    f"目标：根据用户在一段社交媒体{'内容下的评论' if not is_post else '发布的帖子'}，生成一段英文私信，吸引对方关注我们的产品并建立联系。\n"\
                    "\n"\
                    f"任务：我将为你提供【帖子内容】{'和【评论内容】' if not is_post else ''}。请根据这两个信息，生成一段个性化的英文私信。\n"\
                    "\n"\
                    "【写作准则】\n"\
                    "\n"\
                    "开场白（必选，结构分两步）：\n"\
                    "第一步——记忆钩子：先用半句话带出原帖的核心内容或主题，帮用户回忆起当时在说什么。例如原帖是”在家打球不用真的球！“，可以写成“Saw your comment on that 'no ball needed' home setup post…”。禁止直接说“我注意到你帖子/评论了…”，要自然得像刚好刷到同一个帖子的球友。\n"\
                    f"第二步——衔接{'评论' if not is_post else '帖子内容'}：紧接着用你自己的话把{'用户的评论和原帖' if not is_post else '原帖'}的关联讲清楚，证明你真的读懂了。例如用户的内容是”😂😂😂“，你可以说“你的笑哭表情太真实了，第一眼看确实觉得离谱但细想又有点心动“。\n"\
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
                    f"【帖子内容】：{post_text}\n\n"\
                    f"""{f"【评论内容】：{comment_text}" if not is_post else ''}"""
                message = get_text_response_ds("", prompt, api_key=api_keys["deepseek"]["api_key"])
            else:
                message = random.choice(MESSAGES)

            print(f"\n({lead_idx+1}/{len(potential_leads)})")
            print(f"📩 正在和 {username} 建联...")
            print(f'📚 原贴内容:{post_text}\n')
            print(f'📝 评论内容:{comment_text}\n')
            print(f"📝 文案内容: '{message}'")

            if message == '':
                continue

            potential_customer_data.append([username, post_url, post_text, comment_text, message])

        """
            # 调用 chat_x_v0.py 的发送逻辑[cite: 9]
            success = await auto_send_dm(context, profile_url, message)
            
            if success:
                contacted_users.add(username)
                sent_this_round.append(username)
                # 随机冷却，模拟真人行为[cite: 9]
                await asyncio.sleep(random.randint(10, 30))
        end = time.time()
        get_dur(start, end, '建联用户')

        # --- 第四阶段：保存记录 ---[cite: 6]
        if sent_this_round:
            with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
                for user in sent_this_round:
                    f.write(f"{user}\n")
                f.write('\n')
        print(f"\n💾 本轮成功发送 {len(sent_this_round)} 条私信，已记录。\n")

        await context.close()
        """
    
        # 写入文件
        with open(TARGET_USERS_FILE, 'w', newline='', encoding='utf-8') as file:
            potential_customer_data.insert(0, ['uid', 'source url', 'source content', 'source comment', 'message'])
            writer = csv.writer(file)
            writer.writerows(potential_customer_data)


def get_dur(start, end, msg=''):
    duration = end - start
    hours = int(duration // 3600)
    minutes = int((duration % 3600) // 60)
    seconds = duration % 60
    print(f"\n⏱️ {msg}运行时长: {hours:02d}:{minutes:02d}:{seconds:06.3f}\n")

if __name__ == "__main__":
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    print(f'使用账号:{ACCOUNT_NAME}')
    if USE_CHROME:
        print('使用Chrome浏览器')
    else:
        print(f'指纹浏览器USER_ID:{ADSPOWER_USER_ID}\n')
    
    start = time.time()
    asyncio.run(main())
    end = time.time()
    get_dur(start,end)

    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

