import asyncio
import platform
from playwright.async_api import async_playwright

USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"

async def send_tradingview_message(target_user_url, message_text):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=False
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            print(f"正在访问: {target_user_url}")
            await page.goto(target_user_url, wait_until="domcontentloaded")

            # 1. 点击私信按钮
            message_btn = page.locator('button[aria-label="Message"]').first
            await message_btn.click()
            await asyncio.sleep(3)   # 等待弹窗（如果有）

            # 2. 检测错误弹窗
            error_dialog = await page.query_selector('div[data-name="warning-dialog"]')
            if error_dialog:
                # 只提取错误内容区域（class~="content-"）
                content_div = await error_dialog.query_selector('div[class*="content-"]')
                if content_div:
                    error_text = await content_div.text_content()
                else:
                    error_text = await error_dialog.text_content()  # 降级
                print(f"检测到错误弹窗，停止发送：{error_text}")
                # 关闭弹窗（可选）
                ok_btn = page.locator('button[data-qa-id="ok-btn"], button:has-text("Got it")').first
                if await ok_btn.count() > 0:
                    await ok_btn.click()
                await asyncio.sleep(1)
                return -1

            # 3. 无错误，正常发送消息
            chat_input_selector = 'textarea.message-input'
            input_box = page.locator(chat_input_selector)
            await input_box.wait_for(state="visible", timeout=10000)

            # 聚焦与清空策略
            await input_box.click()
            await asyncio.sleep(1.0)
            await page.keyboard.type("Init")
            await asyncio.sleep(0.8)

            modifier = "Meta" if platform.system() == "Darwin" else "Control"
            await page.keyboard.down(modifier)
            await page.keyboard.press("a")
            await page.keyboard.up(modifier)
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.5)

            print(f"开始输入完整消息...")
            await page.keyboard.type(message_text, delay=60)

            # 发送验证（补全机制）
            current_val = await input_box.get_attribute("value") or await input_box.evaluate("el => el.value")
            if len(current_val) < len(message_text) * 0.8:
                print("检测到内容输入不全，尝试补全输入...")
                await input_box.fill(message_text)

            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")
            print("发送流程已尝试完成。")
            await asyncio.sleep(5)

            return 0

        except Exception as e:
            print(f"异常: {e}")
            return -2
        finally:
            await context.close()

if __name__ == "__main__":
    TARGET_URL = "https://www.tradingview.com/u/SamDrnda/"
    MSG = "I see you’re looking for stock ideas and setups in the comments. You want something actionable, right?"
    asyncio.run(send_tradingview_message(TARGET_URL, MSG))