import asyncio
import random, sys, datetime, csv
from playwright.async_api import async_playwright
from itertools import islice

sys.path.append('src/utils')
from common_utils import get_adspower_ws, load_contacted_users

# ==================== 配置区域 ====================
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_1"
FEED_URL = "https://x.com/home"
MAX_USERS = 300

async def mimic_x_human_behavior(page):
    """模拟在 X 首页浏览内容的拟人化行为（参考 chat_v0.py 的 Reddit 逻辑）"""
    try:
        print("📺 正在 X 首页进行拟人化浏览...")
        await page.goto(FEED_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(2, 4))

        scroll_count = random.randint(3, 7)
        for i in range(scroll_count):
            print(f"  👀 浏览页面中 ({i+1}/{scroll_count})")

            scroll_distance = random.randint(400, 900)
            await page.mouse.wheel(0, scroll_distance)

            # 随机停顿
            await asyncio.sleep(random.uniform(2, 5))

            # 20% 概率随机移动鼠标
            if random.random() < 0.2:
                await page.mouse.move(
                    random.randint(200, 500),
                    random.randint(200, 500)
                )

            # 10% 概率点赞当前可见的第一条推文（更拟人）
            if random.random() < 0.1:
                try:
                    like_btn = page.locator('[data-testid="like"]').first
                    if await like_btn.count() > 0:
                        await like_btn.click()
                        print("  ❤️ 随机点了个赞")
                        await asyncio.sleep(random.uniform(1, 2))
                except Exception:
                    pass

        print("✅ 拟人行为结束。")
    except Exception as e:
        print(f"⚠️ 拟人行为执行异常: {e}")
    finally:
        await page.close()


async def check_dm_sent(page):
    messages_locator = page.locator(
        'div[data-testid="dm-message-list"] li div[data-testid^="message-"] span'
    )

    message_count = await messages_locator.count()
    history_texts = []

    if message_count > 0:
        print(f"📊 检测到 {message_count} 条历史交互节点（含时间轴和消息）")
        for i in range(message_count):
            text = await messages_locator.nth(i).inner_text()
            if text.strip():
                history_texts.append(text.strip())

        if history_texts:
            print(f"✅ 确认为已沟通用户。历史消息摘要: {history_texts[-1][:20]}...")
            return True, history_texts

    return False, []


async def auto_send_dm(page, uid, message_text, follow_user=True):

    target_url = f"https://x.com/{uid.replace('@', '')}"

    print(f"🚀 正在前往目标用户主页: {target_url}")
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)

        # --- 关注用户 ---
        if follow_user:
            profile_header_selector = '[data-testid="placementTracking"]'
            follow_button = page.locator(f'{profile_header_selector} button[data-testid$="-follow"]')
            following_indicator = page.locator(f'{profile_header_selector} button[data-testid$="-unfollow"]')

            if await follow_button.count() > 0:
                print("👤 检测到未关注，正在执行关注操作...")
                await follow_button.first.click()
                await page.wait_for_timeout(random.randint(2000, 5000))
                print("✅ 关注成功")
            elif await following_indicator.count() > 0:
                print("ℹ️ 用户已处于关注状态，无需操作")
            else:
                print("⚠️ 未在主页头部找到关注按钮，可能已关注或页面结构变化")

        # --- 私信用户 ---
        dm_button = page.locator('[data-testid="sendDMFromProfile"]')

        if await dm_button.count() == 0:
            print("❌ 无法发送：未找到私信按钮。")
            await page.close()
            return False

        await dm_button.click()
        print("👌🏻 已点击私信按钮，正在等待页面响应...")
        await page.wait_for_timeout(3000)

        # Passcode 验证处理
        pin_selector = '[data-testid="pin-code-input-container"]'
        try:
            await page.wait_for_selector(pin_selector, state="visible", timeout=2000)
            print("🔒 检测到分段 Passcode 验证，开始输入 '1116'...")

            inputs = page.locator(f'{pin_selector} input[type="text"]')
            passcode = "1116"

            if await inputs.count() >= len(passcode):
                for i in range(len(passcode)):
                    await inputs.nth(i).click()
                    await inputs.nth(i).fill(passcode[i])
                    await page.wait_for_timeout(400)
                print("👌🏻 Passcode 填充完成。")
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # 输入私信内容
        textarea_selector = '[data-testid="dm-composer-textarea"]'
        print(f"⏳ 正在等待私信文本框可见...")
        await page.wait_for_selector(textarea_selector, state="visible", timeout=5000)

        is_contacted, history_msg = await check_dm_sent(page)
        if is_contacted:
            print(f'⏭️ 已建联过的用户，跳过！历史最新私信：{history_msg[-1]}')
            return False

        #await page.fill(textarea_selector, message_text)

        message_input = page.locator(textarea_selector)
        # 先点击输入框确保焦点
        await message_input.click()
        await asyncio.sleep(random.uniform(0.3, 0.8))

        message_text = message_text.replace('\n', ' ').replace('\r', ' ')
        # 逐字输入（不带换行）
        for char in message_text:
            await page.keyboard.type(char, delay=random.uniform(0.05, 0.15))
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.2, 0.6))
        await page.wait_for_timeout(random.randint(500, 1000))

        # 发送
        send_button = page.locator('button[data-testid*="send"], button[data-testid*="Send"]').first
        try:
            await send_button.click()
            print('🖱 点击了发送按钮')
        except Exception:
            await page.keyboard.press("Enter")
            print('⌨️ 按了Enter键')

        await page.wait_for_timeout(3000)
        print("✅ 私信成功！")
        return True

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        return False
    finally:
        await page.close()


async def main():
    USE_CHROME = False
    ADSPOWER_USER_ID = 'k1byab0k'
    ACCOUNT_NAME = "Neagle Golf"

    PROJECT_NAME = "golf"
    FLAG = 'top'
    LOG_DIR = f"log/twitter/{PROJECT_NAME}/2026-06-12/{FLAG}"
    TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
    CONTACTED_USERS_FILE = f'files/Twitter/{PROJECT_NAME}/contacted_users.txt'
    START_LINE_IDX = 1

    print(f'使用账号:{ACCOUNT_NAME}')
    if USE_CHROME:
        print('使用Chrome浏览器')
    else:
        print(f'指纹浏览器USER_ID:{ADSPOWER_USER_ID}\n')

    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    print(f'Start from line {START_LINE_IDX} of {TARGET_USERS_FILE}\n')

    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)

    total_rows = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = list(csv.reader(file))
        total_rows = len(reader) - START_LINE_IDX

    sent_this_round = []
    success_cnt = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)

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

            for idx, (uid, _, _, _, msg) in enumerate(islice(reader, START_LINE_IDX, None)):
                print(f"\n{'='*50}")
                print(f"📨 ({idx+1}/{total_rows}) 处理用户: {uid}")

                if uid not in contacted_users:                        
                    page_message = await context.new_page()
                    if msg.startswith('"') and msg.endswith('"'):
                        msg = msg[1:-1]

                    success = await auto_send_dm(page_message, uid, msg)

                    if success:
                        sent_this_round.append(uid)
                        contacted_users.add(uid)
                        success_cnt += 1

                        # ✅ 每次发送后（无论成功与否）都去首页刷一刷，模拟正常使用
                        page_view = await context.new_page()
                        await mimic_x_human_behavior(page_view)
                        await page_view.close()

                        with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
                            f.writelines(f"{uid}\n")

                        if success_cnt > MAX_USERS:
                            break

                        if idx < total_rows - 1:
                            sleep_time = random.randint(5 * 60, 15 * 60)
                            print(f"😴 冷却中，休息 {sleep_time//60} 分 {sleep_time%60} 秒...\n")
                            await asyncio.sleep(sleep_time)
            
            await context.close()

    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    print(f"\n💾 任务结束。本轮成功发送 {len(sent_this_round)} 条私信。")


if __name__ == "__main__":
    asyncio.run(main())