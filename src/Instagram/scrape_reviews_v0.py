import asyncio
import random
from playwright.async_api import async_playwright

USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"

async def scrape_instagram_comments(post_url):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        page = await context.new_page()
        await page.goto(post_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        print("✅ 页面加载完成")

        # 激活评论区（点击帖子内容，确保右侧面板获得焦点）
        try:
            await page.wait_for_selector('div[role="article"]', timeout=10000)
            await page.click('div[role="article"]', timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass

        # 通过 JavaScript 返回滚动容器的 CSS 选择器（而不是元素对象）
        container_selector = await page.evaluate("""
            () => {
                const allDivs = document.querySelectorAll('div');
                let bestCandidate = null;
                let maxScrollHeight = 0;

                for (const div of allDivs) {
                    const style = getComputedStyle(div);
                    const overflowY = style.overflowY;
                    const height = parseInt(style.height);
                    const scrollHeight = div.scrollHeight;

                    if ((overflowY === 'auto' || overflowY === 'scroll') && scrollHeight > height + 100) {
                        if (div.querySelector('a[href^="/"]') && div.querySelector('span[dir="auto"]')) {
                            if (scrollHeight > maxScrollHeight) {
                                maxScrollHeight = scrollHeight;
                                bestCandidate = div;
                            }
                        }
                    }
                }

                if (bestCandidate) {
                    // 优先使用 id
                    if (bestCandidate.id) return '#' + bestCandidate.id;
                    // 否则使用 class（取前两个，避免过于具体）
                    const classes = bestCandidate.className.split(' ').filter(c => c && !c.includes(' ')).slice(0, 2);
                    if (classes.length) return '.' + classes.join('.');
                    // 降级：返回一个通用选择器（可能不精确）
                    return 'div[style*="overflow"]';
                }
                return null;
            }
        """)

        if container_selector:
            print(f"✅ 找到滚动容器选择器: {container_selector}")
            comment_section = page.locator(container_selector).first
            # 验证是否可滚动
            is_scrollable = await comment_section.evaluate("el => el.scrollHeight > el.clientHeight + 10")
            if not is_scrollable:
                print("⚠️ 选择器对应的元素不可滚动，将使用整个页面")
                comment_section = page
        else:
            print("⚠️ 未找到滚动容器，将使用整个页面")
            comment_section = page

        # XPath：兼容文本评论和图片评论
        # 提取评论容器（不再排除内嵌的 a 标签，保留 @ 提及链接）
        comment_xpath = (
            "//div[contains(@class, 'html-div')]"
            "["
                "./div[1]//a[contains(@href, '/')]"
                " and "
                "("
                    "./div[2]//span[@dir='auto']"
                    " or "
                    "./div[2]//img"
                ")"
                " and "
                "not(./div[2]//*[@role='button']) and "
                "not(./div[2]//a and not (./div[2]//a[@role='link'])) and "
                "not(./div[2]//select)"
            "]"
        )

        rows = await page.locator(f'xpath={comment_xpath}').all()

        last_count = 0
        no_increase = 0
        max_rounds = 50

        for round_num in range(1, max_rounds + 1):
            print(f"🔄 第 {round_num} 轮滚动")

            # 点击 "View more comments" 按钮
            more_btn = page.locator('div[role="button"]:has-text("View more comments")')
            if await more_btn.count() > 0:
                try:
                    await more_btn.first.click()
                    await page.wait_for_timeout(2000)
                    print("   点击了 'View more comments'")
                except:
                    pass

            # 滚动到容器底部
            try:
                if comment_section != page:
                    await comment_section.evaluate("el => el.scrollTop = el.scrollHeight")
                else:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception as e:
                print(f"滚动出错: {e}")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            # 等待图片加载
            try:
                await page.wait_for_function(
                    "Array.from(document.querySelectorAll('img')).every(img => img.complete)",
                    timeout=5000
                )
            except:
                pass

            await page.wait_for_timeout(random.randint(2000, 3500))

            # 统计当前评论容器数量
            current_count = await page.locator(f'xpath={comment_xpath}').count()
            print(f"   当前评论容器数: {current_count}")

            more_exists = await more_btn.count() > 0
            if current_count == last_count and not more_exists:
                no_increase += 1
                if no_increase >= 3:
                    print("✅ 已加载所有评论")
                    break
            else:
                no_increase = 0
            last_count = current_count

        # 提取评论
        rows = await page.locator(f'xpath={comment_xpath}').all()
        print(f'\n📊 最终找到评论容器: {len(rows)}')

        results = []
        for row in rows:
            try:
                user_node = row.locator('xpath=./div[1]//a').first
                username = (await user_node.inner_text()).strip()
                user_href = await user_node.get_attribute('href')
                if user_href and user_href.startswith('/'):
                    user_href = f"https://www.instagram.com{user_href}"

                # 提取评论文本或图片标记
                comment_body = ""
                text_spans = await row.locator('xpath=./div[2]//span[@dir="auto"]').all()
                if text_spans:
                    comment_body = (await text_spans[0].inner_text()).strip()
                else:
                    images = await row.locator('xpath=./div[2]//img').all()
                    if images:
                        comment_body = "[图片评论]"
                    else:
                        comment_body = "[无文本]"

                if username and comment_body:
                    results.append({
                        'username': username,
                        'comment': comment_body,
                        'profile_url': user_href
                    })
                    print(f"👤 {username} ({user_href})\n💬 {comment_body}\n")
            except Exception as e:
                print(f"提取单条出错: {e}")

        print(f"\n✅ 共提取 {len(results)} 条评论")
 
        await context.close()

if __name__ == "__main__":
    asyncio.run(scrape_instagram_comments(
        "https://www.instagram.com/p/DW9Wp8KDG8A/"
    ))