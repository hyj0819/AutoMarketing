import asyncio
from openai import timeout
from playwright.async_api import async_playwright
from time import sleep 
import random
import requests
import datetime
import sys, csv
from itertools import islice
sys.path.append('src/utils')
from common_utils import load_contacted_users, get_adspower_ws
from pydantic.type_adapter import P
USER_DATA_DIR = "/Users/coast/Desktop/chrome_profile"  # 需要提前登录的Chrome用户数据目录
MAX_USERS = 1000

# AdsPower API 信息
API_KEY = "4188a4ee49461bef870df28cefc9ecef008bdc717c5b3d88"
BASE_URL = "http://127.0.0.1:50325" # 使用 IP 更稳定


async def mimic_human_behavior(page):
    try:
        print("📺 正在进行拟人化刷视频...")
        await page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(2, 4))

        # 确保页面有焦点，允许键盘操作
        await page.click('body')
        await asyncio.sleep(0.5)

        video_count = random.randint(5, 10)
        
        for i in range(video_count):
            print(f"  👀 观看第 {i+1}/{video_count} 个视频")
            
            # 快速划过（20% 概率）
            if random.random() < 0.2:
                print("    ⏩ 快速划过（不等待）")
                await page.keyboard.press("ArrowDown")
                continue
            
            # 正常观看
            watch_seconds = random.uniform(3, 12)
            await asyncio.sleep(watch_seconds)
            
            # 互动（60% 概率）
            if random.random() < 0.6:
                action = random.choice(["like", "comment", "favorite"])

                if action == "like":
                    print("    ❤️ 随机点赞...")
                    like_btn = page.locator('span[data-e2e="like-icon"]').last
                    if await like_btn.is_visible():
                        await like_btn.click()
                        await asyncio.sleep(random.uniform(0.5, 1.2))
                
                elif action == "comment":
                    print("    💬 打开评论区浏览...")
                    comment_btn = page.locator('span[data-e2e="comment-icon"]').last
                    if await comment_btn.is_visible():
                        await comment_btn.click()
                        await asyncio.sleep(random.uniform(1.5, 3))
                        
                        """
                        # 评论文区滚动
                        for _ in range(random.randint(1, 3)):
                            await page.mouse.wheel(0, random.randint(300, 600))
                            await asyncio.sleep(random.uniform(0.8, 1.5))
                        """
                        
                        # 关闭评论区（再次点击评论按钮）
                        close_btn = page.locator('span[data-e2e="comment-icon"]').last
                        if await close_btn.is_visible():
                            await close_btn.click()
                            await asyncio.sleep(random.uniform(0.5, 1))
                
                elif action == "favorite":
                    print("    🔖 随机收藏...")
                    fav_btn = page.locator('span[data-e2e="favorite-icon"]').last
                    if await fav_btn.is_visible():
                        await fav_btn.click()
                        await asyncio.sleep(random.uniform(0.5, 1.2))
            
            # 滑动到下一个视频（键盘向下）
            if i < video_count - 1:
                await page.keyboard.press("ArrowDown")
                # 滑动后重新聚焦 body，确保后续键盘操作有效
                await page.click('body')
                await asyncio.sleep(random.uniform(0.5, 1.2))
        
        print("✅ 拟人行为结束，准备下一条任务。")
        
    except Exception as e:
        print(f"⚠️ 拟人行为执行异常: {e}")


async def send_direct_message(page, username, message_content):
    try:
        print(f"👤 正在与 {username} 建联...")
        await page.goto(f"https://www.tiktok.com/{username}", wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)
        #sleep(3000)
        
        # 查找关注按钮
        follow_button = page.locator('button[data-e2e="follow-button"]:visible').first
        if await follow_button.count() > 0:
            # 1. 模拟鼠标先移动到按钮上（Hover），停留一下
            await follow_button.hover()
            await page.wait_for_timeout(random.randint(500, 1200))
            
            # 2. 使用 mouse.down 和 mouse.up 替代 click()
            # 这样更像真实的物理点击
            box = await follow_button.bounding_box()
            if box:
                # 在按钮范围内随机取一个点，不要每次都点中心
                click_x = box['x'] + box['width'] * random.uniform(0.3, 0.7)
                click_y = box['y'] + box['height'] * random.uniform(0.3, 0.7)
                
                await page.mouse.move(click_x, click_y, steps=10) # steps增加移动轨迹
                await page.mouse.down()
                await page.wait_for_timeout(random.randint(100, 300))
                await page.mouse.up()
                
            
            await page.wait_for_timeout(random.randint(2000, 4000))

        # 查找消息按钮（选择器需要根据实际页面调整，以下为示例）
        message_button = page.locator('')

        # 等待私信输入框出现
        # 增加显式等待，超时时间设为 15-20 秒
        message_selector = 'button[data-e2e="message-button"]'
        await page.wait_for_selector(message_selector, state="visible", timeout=20000)
        message_button = page.locator(message_selector)
        await message_button.click()

        # 等待私信输入框出现
        input_selector = 'div[contenteditable="true"]'
        await page.wait_for_selector(input_selector, state="visible", timeout=60000)
        message_input = page.locator(input_selector)

        print(f"📝 选中发送文案: '{message_content}'")

        # 输入消息
        #await message_input.fill(message_content)

        # 先点击输入框确保焦点
        await message_input.click()
        await asyncio.sleep(random.uniform(0.3, 0.8))
        
        message_content = message_content.replace('\n', ' ').replace('\r', ' ')
        # 逐字输入（不带换行）
        for char in message_content:
            await page.keyboard.type(char, delay=random.uniform(0.05, 0.15))
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.2, 0.6))

        # ------------------------------------------------------------------
        
        await page.wait_for_timeout(random.randint(1500, 3000)) 
        
        # 定义选择器
        send_btn_selector = 'svg[data-e2e="dm-new-send-btn"]'

        try:
            await page.evaluate(f'''() => {{
                const btn = document.querySelector('{send_btn_selector}');
                if (btn) btn.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true, view: window}}));
            }}''')
            print('🖱 点击了发送按钮')
        except Exception as e:
            await page.keyboard.press("Enter")
            print('⌨️ 按了Enter键')

        await page.wait_for_timeout(3000)
        print("✅ 建联成功！")

        return True, ''
        
    except Exception as e:
        print(f"❌发送失败: {e}")
        return False, str(e)


async def main():
    PROJECT_NAME = "stock"
    FLAG = "buy_stocks"
    LOG_DIR = f"log/tiktok/{PROJECT_NAME}/2026-05-22/{FLAG}"
    TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
    CONTACTED_USERS_FILE = f'files/TikTok/{PROJECT_NAME}/contacted_users.txt'
    START_LINE_IDX = 126

    ADSPOWER_USER_ID = "k1byap97"
    ACCOUNT_NAME = "StockPulseTrader"

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

                        elif 'ERR_SOCKS_CONNECTION_FAILED' in err_msg or 'ERR_CONNECTION_CLOSED' in err_msg:
                            print('🔗 网络连接失败，请检查网络！')
                            break

                    except Exception as e:
                        print(f"  ❌ 私信失败: {e}")
                    finally:
                        await page_message.close()
                else:
                    print(f'已经建联过用户{uid}，跳过！')


                # 严格冷却防止封号（休息5~15分钟）
                sleep_time = random.randint(5 * 60, 15 * 60)
                print(f'睡眠{sleep_time}s')
                await asyncio.sleep(sleep_time)

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

    