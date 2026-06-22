import asyncio
from playwright.async_api import async_playwright
from time import sleep 
import random
import datetime

from pydantic.type_adapter import P
USER_DATA_DIR = "/Users/coast/Desktop/chrome_profile"  # 需要提前登录的Chrome用户数据目录

async def send_direct_message(context, username, message_content):
    async with async_playwright() as p:
        """
        # 使用持久化上下文，保留登录状态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,  # 必须为False，便于观察和处理弹窗
            args=["--disable-blink-features=AutomationControlled"]
        )
        """
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        try:
            await page.goto(f"https://www.tiktok.com/@{username}")
            await page.wait_for_timeout(3000)
            sleep(3000)
            
            # --- 修改后的关注代码逻辑 ---
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
                    
                print(f"👤 已模拟真人点击关注 {username}")
                await page.wait_for_timeout(random.randint(2000, 4000))

            # 查找消息按钮（选择器需要根据实际页面调整，以下为示例）
            message_button = page.locator('button[data-e2e="message-button"]')
            await message_button.click()
            await page.wait_for_timeout(2000)
            
            # 等待私信输入框出现
            message_input = page.locator('div[contenteditable="true"]')
            await page.wait_for_timeout(5000) 
            
            print(f"📝 选中发送文案: '{message_content}'")

            # 输入消息
            await message_input.fill(message_content)
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

            return True
            
        except Exception as e:
            print(f"❌发送失败: {e}")
            return False
        finally:
            await page.close()


async def main():
    LOG_DIR = f"log/tiktok/{str(datetime.date.today())}"
    TARGET_USERS_FILE = "log/tiktok/2026-04-29/potential_customers.txt"
    USER_DATA_DIR = "~/Library/Application Support/Google/Chrome"

    MESSAGES = [
        "I see you’re looking for stock ideas and setups in the comments. You want something actionable, right?",
        "What you’ve been looking for, I can actually get for you.",
        "Must be tiring waiting in comments all the time. Let me help you out.",
        "I have some stock ideas from our creator that I can send you.",
        "I can send you some stock ideas."
    ]

    target_users = [x.strip() for x in open(TARGET_USERS_FILE).readlines()]

    async with async_playwright() as p:
        # 启动持久化环境
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--excludeSwitches=enable-automation",
                  "--use-fake-ui-for-media-stream"]
        )

        for u in target_users:
            message = random.choice(MESSAGES)
            await send_direct_message(context, u, message)


if __name__ == "__main__":
    asyncio.run(main())


    