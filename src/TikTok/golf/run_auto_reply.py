"""
TikTok 评论自动回复系统
功能流程：
1. 搜索关键词视频
2. 爬取视频评论
3. 使用AI判断评论者是否为目标用户
4. 为目标用户生成个性化回复
5. 自动回复该评论
"""

import asyncio
import os, sys
import random
import time
import datetime
import pandas as pd
from time import sleep
import csv
import json

sys.path.append('src/TikTok/common')
# 导入 TikTok 专用模块
from search_keywords_v0 import search_keywords
from scrape_reviews_v0 import scrape_comments
from reply_comments_v0 import batch_reply_comments, extract_comment_data

# 模拟导入（需要替换为实际的DS API调用）
# sys.path.append('src/utils')
# from common_utils import get_text_response_ds, load_contacted_users


# ==================== 配置区域 ====================
PROJECT_NAME = "engagement"
FLAG = "auto_reply"
USER_DATA_DIR = os.path.expanduser("~/Desktop/Chrome_Bot_Data_TK")
LOG_DIR = f"log/tiktok/{PROJECT_NAME}/{str(datetime.date.today())}/{FLAG}"
TARGET_VIDEO_FILE = f"{LOG_DIR}/target_videos.txt"
TARGET_INTERACTIONS_FILE = f"{LOG_DIR}/interactions.csv"

USE_CHROME = True
HEADLESS = False

# 搜索关键词
KEYWORDS = [
    "golf simulator",
    "indoor golf",
    "home golf setup",
]

# AI判断提示词 - 判断用户是否为目标客户
TARGET_USER_PROMPT_TEMPLATE = """【角色】
你是一位拥有 10 年经验的销售和市场分析师，擅长通过社交媒体评论捕捉用户的购买信号。

【任务】
分析以下用户评论，判断该用户是否为高质量的潜在客户。

【判定标准】
请严格基于以下维度进行判断（标准需严格，确保有明确的兴趣信号）：
1. 用户是否直接询问产品、价格、规格或购买方式
2. 用户是否表达了对产品的强烈兴趣或需求
3. 用户是否提到了自己的使用场景（如家里、办公室、商业用途）
4. 用户是否在寻求建议或解决方案
5. 用户是否提到了预算、购买力或实际行动意图
6. 用户是否是初学者或新手用户（更容易转化）
7. 评论是否表达了积极态度和高参与度

【输出格式】
请直接输出 yes 或 no，不需要其他说明。

【原帖内容】: {post_content}

【用户评论】: {user_comment}

【用户ID】: {user_id}
"""

# AI生成回复提示词
REPLY_GENERATION_PROMPT_TEMPLATE = """【角色】
你是一位资深的销售和社区运营专家，擅长通过社交媒体进行友好、自然的互动。你的回复风格：亲切、专业、乐于助人、真诚不推销。

【背景信息】
我们销售高端室内高尔夫模拟器和相关设备，核心优势：
- 专业级精准度和仿真效果
- 多种球场模式和训练工具
- 支持各种家庭和商业环保设置
- 完整的安装和售后服务
- 可定制化方案

【目标】
根据用户的评论，生成一条友好、个性化的回复，以建立联系并引导对方了解我们的产品。

【写作准则】
1. 开场：用自然的方式回应用户的评论，证明你真的读懂了。例如用户说"想在家里装一个"，你可以说"家里装一个真的改变生活质量"。

2. 核心内容（选择最相关的1-2点）：
   - 如果用户询问产品，可以简介介绍一下核心特性
   - 如果用户提到场景，可以分享相关的案例或建议
   - 如果用户是初学者，可以提供友好的入门建议
   - 适当提及我们的专业性或服务优势，但要自然融入

3. 行动号召：
   - 禁止直接说"买我的产品"
   - 可以说"我可以给你看一些实际案例"、"有兴趣的话可以看看我们的产品演示视频"、"如果你想了解更多，我可以私信发给你"
   - 或者问一个开放式问题来引导对话

4. 长度：2-3句话，总字符数不超过200个

5. 语言：英文或用户评论的语言

6. 语气：真诚、专业但不生硬，像一个愿意帮助的专业人士

【原帖内容】: {post_content}

【用户评论】: {user_comment}

【用户ID】: {user_id}

请生成回复内容（前后不需要加引号）：
"""


# ==================== 虚拟DS接口（需要替换为实际API） ====================
async def get_text_response_ds(system_prompt, user_prompt):
    """
    调用DS的文本生成接口
    
    注意：这是一个虚拟实现，实际使用时需要替换为真实的API调用
    例如可以是：OpenAI, Claude, 内部DS服务等
    
    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
    
    Returns:
        str: AI生成的回复文本
    """
    # 实际实现时，这里应该调用真实的AI API
    # 目前返回示例回复以演示流程
    
    print(f"[模拟DS调用] system_prompt: {system_prompt[:50]}...")
    print(f"[模拟DS调用] user_prompt: {user_prompt[:100]}...")
    
    # TODO: 替换为实际的API调用
    # response = await call_your_ds_api(system_prompt, user_prompt)
    
    # 示例回复
    example_replies = [
        "That's exactly what I was thinking! If you're interested, I actually have some great resources on this. Feel free to check out our latest setup guide.",
        "Love the enthusiasm! We've helped many people get their perfect home setup. Would you like to see some real examples?",
        "You're spot on! Have you considered the specific space requirements? I can share some tips based on what we've learned from our community.",
        "Great comment! Our latest version addresses exactly those concerns you mentioned. Happy to show you more details if interested.",
    ]
    
    return random.choice(example_replies)


# ==================== 主程序逻辑 ====================
async def main():
    """主程序入口"""
    
    # 1. 初始化目录
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║       TikTok 评论自动回复系统 - 启动                      ║
║       Project: {PROJECT_NAME:<35}║
║       Time: {str(datetime.datetime.now()):<38}║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        # 启动浏览器
        if USE_CHROME:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context()
        else:
            context = await p.chromium.launch_persistent_context(
                USER_DATA_DIR,
                channel="chrome",
                headless=HEADLESS,
                no_viewport=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
        
        page = await context.new_page()
        
        try:
            # ==================== 第一阶段：搜索视频 ====================
            print(f"\n🔍 第一阶段：搜索视频")
            print("=" * 60)
            
            all_videos = []
            for kw in KEYWORDS:
                print(f"\n📌 搜索关键词: {kw}")
                videos = await search_keywords(page, kw)
                all_videos.extend(videos)
                await asyncio.sleep(random.randint(2, 4))
            
            # 视频去重
            unique_videos = {v['Video_Link']: v for v in all_videos if v['Video_Link']}.values()
            unique_videos = list(unique_videos)[:10]  # 限制数量，防止耗时过长
            
            print(f"\n✅ 搜索完成")
            print(f"   找到 {len(unique_videos)} 个独立视频")
            
            # 保存视频URL
            with open(TARGET_VIDEO_FILE, 'a', encoding='utf-8') as fd:
                for v in unique_videos:
                    fd.write(f"{v['Video_Link']}\n")
            
            # ==================== 第二阶段：爬取评论并处理 ====================
            print(f"\n📝 第二阶段：爬取评论和自动回复")
            print("=" * 60)
            
            all_interactions = []
            
            for v_idx, video in enumerate(unique_videos):
                v_url = video['Video_Link']
                v_title = video.get('Title', video.get('Keyword', ''))
                v_author = video['Author_ID']
                
                print(f"\n({v_idx+1}/{len(unique_videos)}) 处理视频: {v_title[:50]}...")
                print(f"   URL: {v_url}")
                
                try:
                    # 爬取评论
                    print(f"   ⏳ 正在爬取评论...")
                    comments = await scrape_comments(context, v_url)
                    
                    if not comments:
                        print(f"   ⚠️ 此视频无评论或无法获取")
                        continue
                    
                    print(f"   ✅ 成功获取 {len(comments)} 条评论")
                    
                    # 处理每条评论
                    comments_to_reply = []
                    
                    for c_idx, comment in enumerate(comments):
                        uid = comment.get('uid')
                        comment_text = comment.get('text')
                        user_page = comment.get('upage')
                        
                        # 跳过作者自己的评论
                        if uid == v_author:
                            continue
                        
                        # 跳过过短的评论
                        if len(comment_text) < 3:
                            continue
                        
                        print(f"\n   评论 #{c_idx+1}/{len(comments)}: {uid}")
                        print(f"   内容: {comment_text[:60]}...")
                        
                        # 调用AI判断是否为目标用户
                        print(f"   🤖 AI判断中...")
                        judge_prompt = TARGET_USER_PROMPT_TEMPLATE.format(
                            post_content=v_title,
                            user_comment=comment_text,
                            user_id=uid
                        )
                        
                        is_target = await get_text_response_ds(
                            "你是一个精准的目标用户识别专家。请简洁判断。",
                            judge_prompt
                        )
                        
                        is_target_yes = is_target.lower().strip().startswith('yes')
                        
                        if is_target_yes:
                            print(f"   ✅ 确认为目标用户，生成回复...")
                            
                            # 生成回复内容
                            reply_prompt = REPLY_GENERATION_PROMPT_TEMPLATE.format(
                                post_content=v_title,
                                user_comment=comment_text,
                                user_id=uid
                            )
                            
                            reply_text = await get_text_response_ds(
                                "你是一位友好的社区运营专家。请生成自然亲切的回复。",
                                reply_prompt
                            )
                            
                            print(f"   📝 生成的回复: {reply_text[:80]}...")
                            
                            # 加入待回复列表
                            comments_to_reply.append({
                                'comment_text': comment_text,
                                'reply_text': reply_text,
                                'uid': uid,
                                'user_page': user_page
                            })
                            
                            # 记录交互
                            all_interactions.append({
                                'video_url': v_url,
                                'video_title': v_title,
                                'user_id': uid,
                                'user_page': user_page,
                                'user_comment': comment_text,
                                'ai_judgment': is_target,
                                'bot_reply': reply_text,
                                'status': 'pending',
                                'timestamp': datetime.datetime.now().isoformat()
                            })
                        else:
                            print(f"   ⏭️ 非目标用户，跳过")
                        
                        await asyncio.sleep(0.5)
                    
                    # 批量回复评论
                    if comments_to_reply:
                        print(f"\n   🚀 开始批量回复 {len(comments_to_reply)} 条评论...")
                        reply_results = await batch_reply_comments(page, context, v_url, comments_to_reply)
                        
                        # 更新交互状态
                        for result in reply_results:
                            for interaction in all_interactions:
                                if interaction['user_id'] == result['uid']:
                                    interaction['status'] = 'success' if result['success'] else 'failed'
                                    interaction['reply_status'] = result['reason']
                    
                    # 视频间冷却时间
                    await asyncio.sleep(random.randint(30, 60))
                    
                except Exception as e:
                    print(f"   ❌ 处理视频出错: {e}")
                    continue
            
            # ==================== 第三阶段：保存结果 ====================
            print(f"\n💾 第三阶段：保存结果")
            print("=" * 60)
            
            if all_interactions:
                # 转换为DataFrame并保存
                df = pd.DataFrame(all_interactions)
                df.to_csv(TARGET_INTERACTIONS_FILE, index=False, encoding='utf-8-sig')
                print(f"✅ 交互数据已保存: {TARGET_INTERACTIONS_FILE}")
                print(f"   总计 {len(df)} 条互动记录")
                
                # 统计信息
                success_count = len(df[df['status'] == 'success'])
                failed_count = len(df[df['status'] == 'failed'])
                pending_count = len(df[df['status'] == 'pending'])
                
                print(f"\n📊 统计信息:")
                print(f"   ✅ 成功回复: {success_count}")
                print(f"   ❌ 失败: {failed_count}")
                print(f"   ⏳ 待处理: {pending_count}")
                
                # 保存详细日志
                log_file = f"{LOG_DIR}/detailed_log.json"
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump(all_interactions, f, ensure_ascii=False, indent=2)
                print(f"✅ 详细日志已保存: {log_file}")
            else:
                print("⚠️ 没有找到目标用户，无交互记录")
        
        finally:
            await context.close()
    
    print(f"\n{'=' * 60}")
    print("✅ 程序执行完成!")
    print(f"结束时间: {datetime.datetime.now()}")
    print(f"{'=' * 60}\n")



async def main():
    ADSPOWER_USER_ID = "k1byab0k" # "k1byab0k", "k1byap97"
    ACCOUNT_NAME = "NEAGLE_GOLF"

    PROJECT_NAME = "golf"
    LOG_DIR = f"log/tiktok/{PROJECT_NAME}/2026-06-12"
    TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers_reply.csv"
    CONTACTED_USERS_FILE = f'files/TikTok/{PROJECT_NAME}/contacted_users.txt'
    START_LINE_IDX = 1

    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    print(f'使用账号:{ACCOUNT_NAME}; 指纹浏览器USER_ID:{ADSPOWER_USER_ID}\n')
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    print(f'Start from line {START_LINE_IDX} of {TARGET_USERS_FILE}\n')

    total_rows = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = list(csv.reader(file))
        total_rows = len(reader) - START_LINE_IDX

    sent_this_round = []
    success_cnt = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        
        async with async_playwright() as p:
            ws_endpoint = get_adspower_ws(ADSPOWER_USER_ID)
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                # commit 级别：只要开始接收数据就继续，不等待任何渲染
                await page.goto("https://whoer.net", wait_until="commit", timeout=10000)
            except Exception as e:
                print(f"⚠️ 导航触发提醒: {e}")

            for idx, (uid, _, _, _, msg) in enumerate(islice(reader, START_LINE_IDX, None)):
                print(f"({idx+1}/{total_rows})")
                if uid not in contacted_users:
                    try:
                        page_message = await context.new_page()
                        if msg.startswith('"') and msg.endswith('"'):
                            msg = msg[1:-1]
                        success, err_msg = await send_direct_message(page_message, uid, msg)
                        if success:
                            sent_this_round.append(uid)
                            contacted_users.add(uid)
                            # 严格冷却防止封号
                            #await asyncio.sleep(random.randint(5, 15))

                            success_cnt += 1

                            with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
                                f.writelines(f"{uid}\n")

                            if success_cnt >= MAX_USERS:
                                break

                            page_view = await context.new_page()
                            await mimic_human_behavior(page_view)
                            await page_view.close()

                            # 严格冷却防止封号（休息5~15分钟）
                            sleep_time = random.randint(8 * 60, 20 * 60)
                            print(f'睡眠{sleep_time}s')
                            await asyncio.sleep(sleep_time)

                        elif 'ERR_SOCKS_CONNECTION_FAILED' in err_msg or 'ERR_CONNECTION_CLOSED' in err_msg:
                            print('🔗 网络连接失败，请检查网络！')
                            break

                    except Exception as e:
                        print(f"  ❌ 私信失败: {e}")
                    finally:
                        await page_message.close()
                else:
                    print(f'已经建联过用户{uid}，跳过！')

                print('\n\n')

    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    """
    if sent_this_round:
        with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
            for user in sent_this_round:
                f.write(f"{user}\n")
    """

    print(f"\n💾 任务结束。本轮成功发送 {len(sent_this_round)} 条私信。")


if __name__ == "__main__":
    asyncio.run(main())
