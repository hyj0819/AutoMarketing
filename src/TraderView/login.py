import asyncio
from playwright.async_api import async_playwright

# 你的 Chrome 数据目录（建议使用持久化上下文以规避部分验证）
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data" 

async def tradingview_login(mode="email", username="", password=""):
    async with async_playwright() as p:
        # 使用持久化上下文启动 Chrome
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=False
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # 1. 访问登录页面
        # 注意：此处假设你已处于登录对话框弹出的状态或直接访问登录 URL
        print("正在打开登录界面...")
        await page.goto("https://www.tradingview.com/#signin") 

        try:
            if mode == "google":
                # --- 模式 A：Google 账户登录 ---
                print("尝试通过 Google 账户登录...")
                # 源码 a.txt 中 Google 按钮位于 iframe 内
                # 定位包含 Google 登录按钮的 iframe
                google_iframe = page.frame_locator('iframe[title*="Google"]')
                # 点击 iframe 内的登录按钮
                await google_iframe.locator('div[role="button"]').first.click()
                print("已点击 Google 登录，请在弹出的窗口中完成授权。")
                
            else:
                # --- 模式 B：邮箱登录 ---
                print("正在切换至邮箱登录模式...")
                # 1. 在 a.txt 界面点击 "Email" 按钮进入邮箱表单
                email_btn = page.locator('button[name="Email"]')
                await email_btn.wait_for(state="visible")
                await email_btn.click()

                # 2. 在 b.txt 界面输入账号密码
                # 定位用户名/邮箱输入框 (id="id_username")
                username_input = page.locator('input#id_username')
                await username_input.wait_for(state="visible")
                await username_input.fill(username)

                # 定位密码输入框 (id="id_password")
                password_input = page.locator('input#id_password')
                await password_input.fill(password)

                # 3. 点击提交按钮 (Sign in)
                # 源码显示提交按钮包含 submitButton-FIMIWZkg 类名[cite: 14]
                submit_btn = page.locator('button.submitButton-FIMIWZkg')
                print("正在提交登录表单...")
                await submit_btn.click()

            # 留出时间观察登录结果
            await asyncio.sleep(10)

        except Exception as e:
            print(f"登录过程中出现异常: {e}")
        finally:
            # 保持浏览器开启以便手动处理可能的验证码
            # await context.close()
            print("脚本执行完毕。")

if __name__ == "__main__":
    # 使用示例 1：邮箱登录
    # asyncio.run(tradingview_login(mode="email", username="your_email@example.com", password="your_password"))

    # 使用示例 2：Google 登录
    asyncio.run(tradingview_login(mode="google"))