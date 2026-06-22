import asyncio
import csv
import sys
import random
import time
import datetime
from time import sleep

sys.path.append('src/utils')
from search_keywords_v0 import scrape_keyword, parse_args as search_args_def, deduplicate
from scrape_reviews_v0 import scrape_x_comments
from scrape_profile import scrape_user_profile, parse_args as scrape_args_def
#from chat_v0 import auto_send_dm
from common_utils import get_text_response_ds, load_contacted_users, get_adspower_ws

# 基础配置
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_1"
PROJECT_NAME = "stock"
FLAG = 'more_kw'
CONTACTED_USERS_FILE = f'files/Twitter/{PROJECT_NAME}/contacted_users.txt'
MAX_POSTS_PER_KEYWORD = 50  # 每个关键词处理多少个帖子
LATEST_HOURS = 2160  # 抓取近N小时的帖子
SEAECH_BY_LATEST = False
MAX_POST = 10000
USE_PERSONALIZED_MESSAGE = True
LOG_DIR = f"log/twitter/{PROJECT_NAME}/{str(datetime.date.today())}/{FLAG}"
TARGET_POST_FILE = f"{LOG_DIR}/target_posts.txt"
TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"

USE_CHROME = False
ADSPOWER_USER_ID = "k1byap97"  #"k1byab0k"、 "k1byap97"
ACCOUNT_NAME = "StockPulseTrader"   #"Cassian"、 "Coast Cao"

KEYWORDS = [
    "استثمار", # 投资
    "تاسي",  # TASI（沙特交易所主板指数）
    "الأسهم_السعودية", # 沙特股票
    "السوق_السعودي", # 沙特市场
    "TASI"
]

# 大V
# 有个经验，在回复评论的post下的“Discover more”通常会推荐大V的帖子
KOL_PROFILE_LINKS = ['https://x.com/tasi2080', 'https://x.com/LAMMMAH', 'https://x.com/Ezzo_Khrais', 'https://x.com/THEWOLFOFTASI', 'https://x.com/Drfaresalotaibi']


# 话术库
MESSAGES = [
    "I see you’re looking for stock ideas and setups in the comments. You want something actionable, right?",
    "What you’ve been looking for, I can actually get for you.",
    "Must be tiring waiting in comments all the time. Let me help you out.",
    "I have some stock ideas from our creator that I can send you.",
    "I can send you some stock ideas."
]


def is_target_user(is_post, post_content, comment_content=''):
    # AI 意图判定 (参考 scrape_reviews_v0 逻辑)
    prompt = "【角色】\n"\
            "你是一位拥有 10 年经验的金融投资教育领域市场分析师，擅长通过社交媒体的碎片化信息捕捉用户对投资交易课程的购买信号（Buying Signals）\n\n"\
            "【任务】\n"\
            f"我将为你提供帖子的【正文内容】{'和用户的【评论内容】' if not is_post else ''}。请你分析该用户是否在咨询投资或购买股票的意见或者有购买股票/投资交易相关课程的潜在意图。\n\n"\
            "【判定维度】\n"\
            "请基于以下几个维度进行判断（判断标准需要严格一些，得要有比较明确的购买信号）：\n"\
            "1、用户是否在直接询问或寻求推荐具体的投资课程、学习资源、培训项目。\n"\
            "2、用户是否抱怨自己交易亏损、知识不足、缺乏系统方法，或表达了想要提升投资技能的需求。\n"\
            "3、用户是否询问了课程的价格、师资、内容大纲、证书、实战效果或与其它课程的对比。\n"\
            "4、用户是否提到了自己的学习背景（如零基础、有经验但想进阶）、可投入的时间或预算。\n"\
            "5、用户是否表达了强烈的羡慕或“我也想学/我也需要这种课程”的愿望。\n"\
            "6、用户是否在咨询购买股票或者投资意见。\n"\
            "7、用户是否为投资小白。\n"\
            "【输出格式】\n"\
            "请直接输出yes或者no，不需要其他说明。\n\n"\
            f"【正文内容】: {post_content}\n\n"\
            f"{f'【评论内容】: {comment_content}' if not is_post else ''}"
    is_potential = get_text_response_ds("你是一个获客专家。请简洁判断。", prompt)

    return is_potential


async def main():
    # 1. 初始化
    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    sent_this_round = []
    
    # 获取搜索参数
    search_args = search_args_def()
    search_args.hours = LATEST_HOURS
    search_args.search_by_latest = SEAECH_BY_LATEST
    search_args.max_post = MAX_POST

    # 爬取用户主页的参数
    scrape_args = scrape_args_def()
    scrape_args.hours = LATEST_HOURS
    scrape_args.max_post = MAX_POST

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

        search_page = await context.new_page()
        # --- 第一阶段：搜索帖子
        all_posts = []
        for kw in KEYWORDS:
            search_args.keywords = kw
            print(f"🔍 正在搜索关键词: {kw}")
            print(f'Search args:{search_args}')

            start = time.time()

            posts = await scrape_keyword(search_page, search_args)

            end = time.time()
            get_dur(start, end, f'搜索{kw}相关帖子')

            all_posts.extend(posts)
        search_page.close()

        srape_page = await context.new_page()
        for profile_link in KOL_PROFILE_LINKS:
            posts = scrape_user_profile(srape_page, profile_link, scrape_args)
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
        scrape_review_page = context.new_page()
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

            is_target = is_target_user(is_post=True, post_content=post_text)

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
            comments = await scrape_x_comments(scrape_review_page, post_url, LOG_DIR)
            
            for comment in comments:
                username = comment['uid'] # 例如 @user123
                profile_url = comment['upage']
                comment_text = comment['text']
                comment_ts = int(datetime.datetime.strptime(comment['timestamp'], "%Y-%m-%dT%H:%M:%S.%fZ").timestamp())

                if post_text.strip() == "" or comment_text.strip() == "": continue

                # 排除已联系过的用户[cite: 6]
                if username in contacted_users or username in added_targets: continue

                is_target = is_target_user(is_post=False, post_content=post_text, comment_content=comment_text)

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
                        "你是一位资深的金融投资教育行业海外营销专家，擅长通过社交媒体（Reddit/Twitter/Discord）进行精准截流获客。你的话术风格：专业、像圈内交易伙伴、乐于助人、不生硬推销。\n"\
                        "\n"\
                        "【背景】\n"\
                        "我司提供实战型股票投资与交易策略课程（Stock Investment & Trading Course）。\n"\
                        "产品核心优势：\n"\
                        "1. 完整交易系统：涵盖趋势跟踪、动量交易、价值投资、波段操作等多种策略，适配不同市场环境。\n"\
                        "2. 实盘案例库：收录近3年50+高胜率交易案例，包含入场逻辑、持仓管理、退出信号完整拆解。\n"\
                        "3. 风险管理框架：独创仓位计算公式+动态止损规则，帮助学员将单笔亏损控制在总资金2%以内。\n"\
                        "4. 实时信号社区：交易日推送盘前简报、盘中异动提醒、关键支撑/压力位更新（不开盘时段提供复盘要点）。\n"\
                        "5. 量化回测数据：所有策略均经5年以上历史数据回测，并附夏普比率、最大回撤、胜率等关键指标。\n"\
                        "6. 新手保护计划：模拟交易比赛+每月两场直播答疑（含录像回放），确保零基础也能逐步上手。\n"\
                        "7. 工具包：自动计算盈亏比的风险回报比表格、交易日志模板、财报日历提醒工具。\n"\
                        "8. 专属社群：仅限学员加入的Discord频道，禁止喊单刷屏，只讨论逻辑与复盘，氛围严肃认真。\n"\
                        "\n"\
                        "目标：根据用户在一段社交媒体内容下的评论，生成一段英文私信，吸引对方关注我们的课程/服务并建立联系。\n"\
                        "\n"\
                        f"任务：我将为你提供【帖子内容】{'和【评论内容】' if not is_post else ''}。请根据这两个信息，生成一段个性化的英文私信。\n"\
                        "\n"\
                        "【写作准则】\n"\
                        "\n"\
                        "开场白（必选，结构分两步）：\n"\
                        "第一步——记忆钩子：先用半句话带出原帖的核心内容或主题，帮用户回忆起当时在说什么。例如原帖是“仓位被套了怎么办？”，可以写成“Saw your take on that 'bag holding' thread…”。禁止直接说“我注意到你评论了…”，要自然得像刚好在同一投资社区里碰到的交易者。\n"\
                        "第二步——衔接评论：紧接着用你自己的话把用户的评论和原帖的关联讲清楚，证明你真的读懂了。例如用户评论是“😂 我也被A股割过”，你可以说“你那个笑哭的表情太真实了，上个月我自己复盘也是这种感觉”。\n"\
                        "\n"\
                        "禁止的做法：\n"\
                        "- 只孤立地引用评论中的单词（如”'TA'—great call!“）\n"\
                        "- 以”Dear“或”I noticed you commented on…“开头\n"\
                        "- 禁止直接生搬硬套上述样例中的词，要结合原内容和评论来生成。\n"\
                        "\n"\
                        "隐形推销：\n"\
                        "- 禁止直接说”买我们的课程“或”报名我们的服务“\n"\
                        "- 要说”我这里正好有一个解决这个困惑的案例/视频/框架，你想看看吗？“或”如果你好奇如何系统地处理这类交易，我可以发一份我们内部用的复盘模板给你“\n"\
                        "- 不涉及与竞品的直接对比（如“比某某老师强”），只低调说明自家产品相关的解决思路\n"\
                        "- 每次选1-2个与帖子/评论场景最相关的产品优势自然嵌入，不要罗列全部卖点\n"\
                        "\n"\
                        "长度：严格控制在3-4句话，总字符数（含空格和标点）不超过350个。\n"\
                        "\n"\
                        "语气：专业但亲切，像一个乐于分享实战经验的交易老手，不生硬推销。\n"\
                        "\n"\
                        "语言：英文。\n"\
                        "\n"\
                        "其他： 若无必须，整个私信的前后不用加双引号\n"\
                        "\n"\
                        f"【帖子内容】：{post_text}\n\n"\
                        f"""{f"【评论内容】：{comment_text}" if not is_post else ''}"""
                message = get_text_response_ds("", prompt)
            else:
                message = random.choice(MESSAGES)

            print(f"\n({lead_idx+1}/{len(potential_leads)})")
            print(f"📩 正在和 {username} 建联...")
            print(f'📚 原贴内容:{post_text}\n')
            print(f'📝 评论内容:{comment_text}\n')
            print(f"📝 文案内容: '{message}'")

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

