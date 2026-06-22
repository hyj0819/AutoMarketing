import asyncio
from openai import timeout
from playwright.async_api import async_playwright
import random
import datetime
import csv
import sys, requests
from itertools import islice
sys.path.append('src/utils')
from common_utils import load_contacted_users, get_adspower_ws

# ==================== 配置区域 ====================
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"  # 你的本地Chrome用户数据目录
MAX_USERS = 300


# 模拟拟人化浏览的 Reddit 目标（可以是首页或某个 Subreddit）
FEED_URL = "https://www.reddit.com/"


async def mimic_reddit_human_behavior(page):
    """模拟在 Reddit 首页浏览内容的拟人化行为"""
    try:
        print("📺 正在 Reddit 进行拟人化浏览...")
        await page.goto(FEED_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(2, 4))

        # 模拟点击页面确保聚焦
        #await page.mouse.click(300, 300)
        
        scroll_count = random.randint(3, 7)
        for i in range(scroll_count):
            print(f"  👀 浏览页面中 ({i+1}/{scroll_count})")
            
            # 随机滚动距离
            scroll_distance = random.randint(400, 900)
            await page.mouse.wheel(0, scroll_distance)
            
            # 随机停顿观看
            await asyncio.sleep(random.uniform(2, 5))
            
            # 20% 概率左右小范围移动鼠标
            if random.random() < 0.2:
                await page.mouse.move(random.randint(200, 500), random.randint(200, 500))

        print("✅ 拟人行为结束。")
    except Exception as e:
        print(f"⚠️ 拟人行为执行异常: {e}")

async def send_reddit_dm(page, target_user_id, message_content):
    try:
        target_user_url = f"https://www.reddit.com/user/{target_user_id}"
        print(f"🌐 正在访问用户主页: {target_user_url}")
        await page.goto(target_user_url, wait_until="domcontentloaded")

        # 1. 关注用户（发私信前先关注，提高通过率）
        print("👤 正在检查关注状态...")
        try:
            # follow-button 组件内有两个 slot：button-follow 和 button-unfollow
            # 只有当前未关注时，button-follow slot 内的按钮才可见
            follow_btn = page.locator('[slot="button-follow"] button[data-testid="follow-button"]')
            await follow_btn.wait_for(state="attached", timeout=8000)

            # 判断是否已关注：若 unfollow 按钮可见则已关注
            unfollow_btn = page.locator('[slot="button-unfollow"] button[data-testid="follow-button"]')
            already_following = await unfollow_btn.is_visible()

            if already_following:
                print("➕ 已关注该用户，跳过关注步骤。")
            else:
                print("➕ 正在关注用户...")
                await follow_btn.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(0.5, 1.2))
                await follow_btn.click()
                await asyncio.sleep(random.uniform(1.0, 2.0))
                print("👤 关注成功！")
        except Exception as e:
            print(f"⚠️ 关注步骤异常（继续发私信）: {e}")

        # 2. 定位私信按钮，提取独立聊天链接
        print("🔍 正在提取独立聊天界面链接...")
        chat_btn = page.locator('reddit-chat-anchor a[data-testid="private-chat-button"]')
        await chat_btn.wait_for(state="attached", timeout=15000)
        
        chat_url = await chat_btn.get_attribute("href")
        
        if chat_url:
            print(f"🔗 提取成功: {chat_url}")
            print("🚀 直接跳转到专属聊天界面...")
            # 直接访问 chat.reddit.com 的专属链接
            await page.goto(chat_url, wait_until="domcontentloaded")
        else:
            print("⚠️ 未找到 href 属性，尝试传统 JS 点击...")
            await chat_btn.evaluate("node => node.click()")

        # 3. 等待聊天独立页面渲染
        print("⏳ 等待聊天界面加载...")
        await asyncio.sleep(6) # chat.reddit.com 加载较重，给点缓冲时间

        # 4. 定位聊天框容器
        # 此时页面已经位于 chat.reddit.com，定位输入框组件
        composer = page.locator('rs-message-composer').last
        await composer.wait_for(state="attached", timeout=20000)

        input_selector = 'textarea[name="message"]'
        message_input = composer.locator(input_selector)

        print("🔧 正在强制激活输入框...")
        # 强制解除可能存在的隐藏/禁用属性
        await message_input.evaluate("""node => {
            node.style.display = 'block';
            node.style.visibility = 'visible';
            node.style.opacity = '1';
            node.disabled = false;
            node.focus();
        }""")
        
        # 先点击输入框确保焦点
        await message_input.click()
        await asyncio.sleep(random.uniform(0.3, 0.8))

        # 5. 输入内容
        print("✍️ 正在输入...")
        #await message_input.fill(message_content)
        message_content = message_content.replace('\n', ' ').replace('\r', ' ')
        # 逐字输入（不带换行）
        for char in message_content:
            await page.keyboard.type(char, delay=random.uniform(0.05, 0.15))
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.2, 0.6))
        await asyncio.sleep(1)

        # 6. 点击发送
        send_btn = composer.locator('button[aria-label="Send message"]')
        
        # 检查发送按钮状态
        is_disabled = await send_btn.get_attribute("disabled")
        if is_disabled is not None:
            print("⚠️ 发送按钮禁用，追加空格触发前端事件...")
            await message_input.focus()
            await page.keyboard.press("Space")
            await asyncio.sleep(1)

        print("🚀 点击发送...")
        await send_btn.click(force=True)
        
        print("✅ 私信发送成功！")
        return True, ""

    except Exception as e:
        print(f"❌ 流程异常: {e}")
        return False, str(e)

async def main():
    USE_CHROME = False
    ADSPOWER_USER_ID = "k1byap97"
    ACCOUNT_NAME = "One-Abrocoma-5107"
    ADSPOWER_USER_ID = "k1byab0k"  #"k1byab0k"、 "k1byap97"
    ACCOUNT_NAME = "StockPulseTrader"  #"StockPulseTrader"、 "One-Abrocoma-5107"
    PROJECT_NAME = "stock"
    FLAG='new'
    LOG_DIR = f"log/reddit/{PROJECT_NAME}/2026-05-20/{FLAG}"
    TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
    CONTACTED_USERS_FILE = f'files/Reddit/{PROJECT_NAME}/contacted_users.txt'
    START_LINE_IDX = 2

    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    print(f'使用账号:{ACCOUNT_NAME}')
    if USE_CHROME:
        print('使用Chrome浏览器')
    else:
        print(f'指纹浏览器USER_ID:{ADSPOWER_USER_ID}\n')
    print(f'Start from line {START_LINE_IDX} of {TARGET_USERS_FILE}\n')

    sent_this_round = []
    success_cnt = 0
    
    total_rows = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)

        rows = list(reader)
        total_rows = len(rows) - START_LINE_IDX

    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)

        async with async_playwright() as p:
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

            page = context.pages[0] if context.pages else await context.new_page()
            try:
                # commit 级别：只要开始接收数据就继续，不等待任何渲染
                await page.goto("https://whoer.net", wait_until="commit", timeout=10000)
            except Exception as e:
                print(f"⚠️ 导航触发提醒: {e}")

            for idx, (uid, _, _, _, msg) in enumerate(islice(reader, START_LINE_IDX, None)):
                print(f"({idx+1}/{total_rows})")
                page_message = await context.new_page()
                if uid not in contacted_users:
                    try:
                        if msg.startswith('"') and msg.endswith('"'):
                            msg = msg[1:-1]
                        success, err_msg = await send_reddit_dm(page_message, uid, msg)
                        if success:
                            sent_this_round.append(uid)
                            contacted_users.add(uid)

                            await asyncio.sleep(random.randint(1, 3))

                            success_cnt += 1

                            with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
                                f.writelines(f"{uid}\n")

                            if success_cnt > MAX_USERS:
                                break

                            page_view = await context.new_page()
                            await mimic_reddit_human_behavior(page_view)
                            await page_view.close()

                            # 严格冷却防止封号（休息3~5分钟）
                            if idx < total_rows - 1:
                                sleep_time = random.randint(3 * 60, 5 * 60)
                                print(f'睡眠{sleep_time}s')
                                await asyncio.sleep(sleep_time)


                        elif 'ERR_SOCKS_CONNECTION_FAILED' in err_msg or 'ERR_CONNECTION_CLOSED' in err_msg:
                            print('🔗 网络连接失败，请检查网络！')
                            break

                    except Exception as e:
                        print(f"  ❌ 私信失败: {e}")
                else:
                    print(f'已经建联过用户{uid}，跳过！')

                await page_message.close()

                print('\n\n')

    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')


    print(f"\n💾 任务结束。本轮成功发送 {len(sent_this_round)} 条私信。")


if __name__ == "__main__":
    asyncio.run(main())