import asyncio
import random
from playwright.async_api import async_playwright

USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data"

async def scrape_pinterest_comments(url):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = await context.new_page()
        print(f"正在访问: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        # 1. 展开评论区
        try:
            collapse_btn = page.locator('[data-test-id="collapse-button"]')
            if await collapse_btn.count() > 0:
                await collapse_btn.first.click(force=True)
                await page.wait_for_timeout(2000)
        except: pass

        all_comments_data = []
        seen_ids = set()

        print("正在执行最终深度解析（补全被误删的回复者姓名）...")
        for _ in range(12): 
            new_items = await page.evaluate("""
                () => {
                    const results = [];
                    const containers = document.querySelectorAll('[data-test-id="author-and-comment-container"]');
                    
                    containers.forEach(container => {
                        const textNodes = container.querySelectorAll('[data-test-id="text-container"]');
                        if (textNodes.length === 0) return;
                        const commentText = textNodes[textNodes.length - 1].innerText.trim();

                        const row = container.closest('.qtP9fl') || container.closest('.wl0pCr') || container.parentElement.parentElement;
                        if (!row) return;

                        const authorLink = row.querySelector('a[href*="/"]');
                        if (authorLink && commentText) {
                            let nickname = "";
                            
                            // 1. 尝试从头像属性获取（最准）
                            const img = row.querySelector('img');
                            const svg = row.querySelector('svg[aria-label]');
                            if (img && img.getAttribute('alt')) {
                                nickname = img.getAttribute('alt').replace('Avatar for ', '').trim();
                            } else if (svg && svg.getAttribute('aria-label')) {
                                nickname = svg.getAttribute('aria-label').replace('Avatar for ', '').trim();
                            }

                            // 2. 如果头像没拿到，或者拿到的名字是“回应/回复”
                            const blacklist = ["回应", "回复", "Reply", "Replies", "Share", "分享"];
                            if (!nickname || blacklist.includes(nickname)) {
                                // 强制寻找该行内带有 dir="auto" 的 span，这通常是用户名的纯文本位置
                                const nameSpan = row.querySelector('span[dir="auto"]');
                                if (nameSpan && !blacklist.includes(nameSpan.innerText.trim())) {
                                    nickname = nameSpan.innerText.trim();
                                } else {
                                    // 最后的保底：取链接的 innerText
                                    const rawLinkText = authorLink.innerText.trim();
                                    if (!blacklist.includes(rawLinkText)) {
                                        nickname = rawLinkText;
                                    }
                                }
                            }

                            if (commentText && nickname && !blacklist.includes(nickname)) {
                                results.push({
                                    nickname: nickname,
                                    author_url: authorLink.href,
                                    comment: commentText
                                });
                            }
                        }
                    });
                    return results;
                }
            """)

            for item in new_items:
                unique_id = f"{item['author_url']}_{item['comment']}"
                if unique_id not in seen_ids:
                    all_comments_data.append(item)
                    seen_ids.add(unique_id)
                    print(f"成功捕获: [{item['nickname']}] -> {item['comment'][:15]}...")

            await page.evaluate('''
                const c = document.querySelector('[data-test-id="aggregated-comment-list"]') || 
                          document.querySelector("[id*='comments-thread-container']");
                if (c) c.scrollTop += 800;
            ''')
            await page.wait_for_timeout(random.randint(2000, 3000))

        print("\n" + "="*80)
        print(f"抓取完成：最终捕获 {len(all_comments_data)} 条记录")
        for i, item in enumerate(all_comments_data, 1):
            print(f"[{i}] 用户: {item['nickname']}")
            print(f"    主页: {item['author_url']}")
            print(f"    内容: {item['comment']}")
            print("-" * 40)
        print("="*80)

        await context.close()

if __name__ == "__main__":
    asyncio.run(scrape_pinterest_comments("https://www.pinterest.com/pin/70437490478522/"))