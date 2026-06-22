import asyncio
from playwright.async_api import async_playwright
import json
from common_utils import get_text_response_ds, parse_cookie_string

# 🎯 替换为你浏览器里实际的值
MY_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

# 🎯 将你导出的 JSON Cookie 存为本地文件 cookies.json 或直接粘贴在这里
# 注意：格式必须是列表 [{}, {}]
MY_COOKIES = parse_cookie_string("""ZfxkGC4RRxNhQZKnMN5AxFVcjHk=cFdYE5g42lLGYt0A6azGHpeLzG4; myNh3gF9l5fyJXPvquaQ4xNSmcM=1776069480; faVC2nfqrEoWz3ER2WOWA7S0lz4=1776073080; doCRQP8t46hO5Op0NZ12ltU5vRU=IgFhyIzLknvXuxq6t-cBzqFLQHs; TZ_d3TWQ9BMWU_FfeLCUEesOHzw=gtyV_Qr-5Hw7oYVRApOL9qI6_MY; bCixbTdSQkrwKp70YjA4pLLwRXk=1776069484; 73ZPMs24DA_5Pe194o4JnJVXRy0=1776073084; G-lXmx7PAw_NkUTivk5QmxPMVig=-FhjLOesJ4fHe2cviAxk7gZs1X0; g7mKtWXpwZv7_-K7nxfIWpGmWP8=Fyri_yhmmKBulEEShv8By8ij3iI; Kcol3oiDotrqNZoRj_UW_tc49yU=1776072208; IU1PJffXMgGALrspc47PY4dXJEc=1776075808; aLu1L5TxMmCXzl9Ecs8Elm5BjfY=bTojjyGdEW8ZLfCbD2n1Edsn-Hs; 0ueoahi8TJXFNG7ih8AJh1SSaMk=gtyV_Qr-5Hw7oYVRApOL9qI6_MY; VPkbvTOaf0DoCtJwnfk5UpBJ4lY=1776072211; OIOym1qUoD7PyQsCzXx0OKHXUVE=1776075811; -1yhkVOzPAOfIDOXzPSigE8oze8=A4v_utym2q-ek2g-q_GhMYu65KU""")

POST_URL = "https://xcancel.com/lululemon/status/1819126454229389633"

async def scrape_xcancel_comments():
    async with async_playwright() as p:
        # 即使使用了 Cookie，建议第一次运行先 headless=False，观察是否依然 503
        browser = await p.chromium.launch(headless=False)
        
        # 1. 创建 Context 时注入 User-Agent
        context = await browser.new_context(
            user_agent=MY_USER_AGENT,
            viewport={'width': 1920, 'height': 1080}
        )

        # 2. 注入手动获取的 Cookies
        await context.add_cookies(MY_COOKIES)

        page = await context.new_page()
        
        # 3. 绕过常见的自动化检测
        await page.add_init_script("delete navigator.__proto__.webdriver")

        print(f"🚀 携带人工身份信息访问: {POST_URL} ...")
        
        try:
            # 使用 networkidle 确保 JS 加载完成
            response = await page.goto(POST_URL, wait_until="networkidle", timeout=60000)
            
            if response.status == 503:
                print("❌ 依然返回 503！请在打开的浏览器窗口手动点击一下页面，看是否触发了验证码。")
                await asyncio.sleep(10) # 给你 10 秒钟手动操作时间
            
            await page.wait_for_selector(".replies", timeout=15000)
        except Exception as e:
            print(f"⚠️ 页面进入失败: {e}")
            await browser.close()
            return []

        # --- 滚动加载逻辑 ---
        comments = []
        seen_texts = set()
        prev_count = 0

        print("📜 身份识别成功，开始滚动抓取全部评论...")
        
        for attempt in range(50):
            replies = page.locator(".reply")
            current_count = await replies.count()
            
            # 实时解析新评论
            for i in range(current_count):
                try:
                    node = replies.nth(i)
                    text = await node.locator(".tweet-content").first.inner_text()
                    if text not in seen_texts:
                        user_id = await node.locator(".username").first.inner_text()
                        comments.append({
                            "user": await node.locator(".fullname").first.inner_text(),
                            "uid": user_id.replace("@", ""),
                            "text": text,
                            "upage": f"https://xcancel.com/{user_id.replace('@', '')}"
                        })
                        seen_texts.add(text)
                except:
                    continue
            
            print(f"迭代 {attempt+1}: 已抓取 {len(comments)} 条唯一评论")

            # 滚动到最后一条评论以加载更多内容
            if current_count > 0:
                await replies.nth(current_count - 1).scroll_into_view_if_needed()
                await page.wait_for_timeout(2000) # 模拟真人停顿阅读
            
            # 如果连续抓取数量没变，说明到底了
            if len(comments) == prev_count and len(comments) > 0:
                # 最后的倔强：再往下滚 1000 像素看一眼
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(2000)
                if len(comments) == prev_count:
                    print("✅ 评论加载完毕")
                    break
            
            prev_count = len(comments)

        await browser.close()
        return comments


async def main():
    # 1. 抓取原始数据
    raw_comments = await scrape_xcancel_comments()
    print(f"\n🎉 共抓取到评论数: {len(raw_comments)}")

    final_ret = []

    # 2. 调用模型判定购买意愿
    for c in raw_comments:
        prompt_input = f"You are a helpful assistant analyzing X/Twitter replies. Determine if the user is a potential customer for the brand based on this comment: {c['text']}"
        system_instruction = "Return only 'yes' or 'no'. Slightly relaxed judgment criteria."
        
        try:
            # 调用你原有的模型接口
            ret = get_text_response_ds(prompt_input, system_instruction)
            ret = ret.lower().strip()
            
            print(f"User: {c['user']} | Text: {c['text'][:30]}... | Intent: {ret}")

            if 'yes' in ret:
                final_ret.append({
                    "Reviewer": c['user'],
                    "Reviewer UID": c['uid'], 
                    "Reviewer page": c['upage'],
                    "Comment": c['text']
                })
        except Exception as e:
            print(f"AI 判定出错: {e}")

    # 3. 输出结果
    print("\n" + "="*50)
    print("🔥 具有购买意愿的潜在客户列表：")
    print(json.dumps(final_ret, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())