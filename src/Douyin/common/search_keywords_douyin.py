import asyncio
import random
from playwright.async_api import Page

MAX_SCROLLS = 10
STUCK_THRESHOLD = 3


def _normalize_douyin_url(href: str) -> str:
    """统一处理抖音链接，避免重复拼接域名"""
    if not href:
        return ""
    href = href.strip()
    if href.startswith('http://') or href.startswith('https://'):
        return href
    if href.startswith('//'):
        return f"https:{href}"
    if href.startswith('/'):
        return f"https://www.douyin.com{href}"
    return f"https://www.douyin.com/{href}"

# 多版本选择器兼容（抖音频繁更新 DOM 结构）
ITEM_SELECTORS = (
    'div[class*="DivItemContainer"]',
    'div[class*="DivVideoCard"]',
    'div[class*="VideoCard"]',
    'div[class*="search-result"] a[href*="/video/"]',
    'a[href*="/video/"]',
)


async def _diagnose_page(page: Page, log_fn=None):
    """诊断当前页面状态，输出可用于调试选择器的信息"""
    def _log(level, msg):
        print(msg)
        if log_fn:
            try:
                log_fn(level, msg)
            except Exception:
                pass

    url = page.url
    title = await page.title()
    _log("info", f"🔍 [诊断] 页面URL: {url}")
    _log("info", f"🔍 [诊断] 页面标题: {title}")

    # 检测是否有登录弹窗或验证码
    login_signals = await page.query_selector_all(
        '[class*="login"], [class*="Login"], [class*="verify"], [class*="Verify"], [class*="captcha"]'
    )
    if login_signals:
        _log("warn", f"🔍 [诊断] 检测到登录/验证弹窗元素 {len(login_signals)} 个，尝试关闭...")
        # 尝试按 Escape 关闭弹窗
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)

    # 检测视频链接数量（最可靠的信号）
    video_links = await page.query_selector_all('a[href*="/video/"]')
    _log("info", f"🔍 [诊断] 页面中 a[href*='/video/'] 链接数: {len(video_links)}")

    # 尝试多种选择器，报告哪些能匹配到
    for selector in ITEM_SELECTORS:
        try:
            count = len(await page.query_selector_all(selector))
            if count > 0:
                _log("info", f"🔍 [诊断] 选择器 `{selector}` 匹配到 {count} 个元素 ✅")
        except Exception:
            pass

    # 如果没有匹配到任何选择器，输出页面 body 的前 2000 字符用于分析
    if len(video_links) == 0:
        try:
            body_html = await page.evaluate("document.body.innerHTML.substring(0, 2000)")
            _log("warn", f"🔍 [诊断] 页面 body 片段(前2000字符):\n{body_html[:2000]}")
        except Exception as e:
            _log("warn", f"🔍 [诊断] 无法获取页面HTML: {e}")


async def get_video_data(container, keyword):
    """解析抖音搜索结果卡片"""
    try:
        # 优先从容器内查找视频链接
        video_a = await container.query_selector('a[href*="/video/"]')
        v_link = ""
        if video_a:
            href = await video_a.get_attribute('href')
            v_link = _normalize_douyin_url(href)

        author_a = await container.query_selector('a[href*="/user/"]')
        home_link = ""
        author_id = ""
        if author_a:
            href = await author_a.get_attribute('href')
            if href:
                home_link = _normalize_douyin_url(href)
                author_id = href.split('?')[0].split('/')[-1].replace('@', '')

        # 多版本标题选择器
        video_title = ""
        for title_sel in (
            'span[data-e2e="search-card-video-caption"]',
            'span[class*="caption"]',
            'span[class*="title"]',
            'p[class*="desc"]',
        ):
            desc_elem = await container.query_selector(title_sel)
            if desc_elem:
                video_title = (await desc_elem.inner_text()).strip().replace('\n', ' ')
                if video_title:
                    break

        # 如果容器级别没拿到标题，尝试从整个容器取文本
        if not video_title:
            try:
                video_title = (await container.inner_text()).strip().replace('\n', ' ')[:200]
            except Exception:
                pass

        stats_elem = await container.query_selector('strong[data-e2e="video-views"]')
        views = 0
        if stats_elem:
            text = (await stats_elem.inner_text()).strip()
            if '万' in text:
                views = int(float(text.replace('万', '')) * 10000)
            elif 'K' in text:
                views = int(float(text.replace('K', '')) * 1000)
            elif 'M' in text:
                views = int(float(text.replace('M', '')) * 1000000)
            else:
                try:
                    views = int(text.replace(',', ''))
                except:
                    views = 0

        return {
            "Keyword": keyword,
            "Author_ID": author_id,
            "Title": video_title,
            "Author_Home": home_link,
            "Video_Link": v_link,
            "Stats": views,
        }
    except Exception as e:
        print(f"解析单个卡片出错: {e}")
        return None


async def search_keywords(page, keyword, max_items=None, log_fn=None):
    """搜索关键词并采集视频列表（抖音版）"""
    def _log(level, msg):
        print(msg)
        if log_fn:
            try:
                log_fn(level, msg)
            except Exception:
                pass

    url = f"https://www.douyin.com/search/{keyword}?type=video"
    _log("info", f"🌐 正在检索关键词: {keyword}，链接：{url}")

    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(5)

    # 页面诊断：检测登录状态、选择器匹配情况
    await _diagnose_page(page, log_fn)

    captured_links = set()
    results = []
    consecutive_zero_count = 0

    # 动态检测可用选择器
    active_selector = None
    for selector in ITEM_SELECTORS:
        try:
            count = len(await page.query_selector_all(selector))
            if count > 0:
                active_selector = selector
                _log("info", f"✅ 使用选择器: `{selector}`（匹配 {count} 个元素）")
                break
        except Exception:
            pass

    if not active_selector:
        # 回退：直接通过视频链接采集
        _log("warn", "⚠️ 未匹配到任何容器选择器，回退到视频链接直采模式")
        active_selector = 'a[href*="/video/"]'

    ITEM_SELECTOR = active_selector

    for i in range(MAX_SCROLLS):
        try:
            await page.wait_for_selector(ITEM_SELECTOR, state="attached", timeout=10000)
        except Exception as e:
            _log("warn", f"⚠️ 轮次 {i+1}: 未检测到元素")

        current_containers = await page.query_selector_all(ITEM_SELECTOR)
        if current_containers:
            try:
                await current_containers[-1].scroll_into_view_if_needed()
                await asyncio.sleep(random.randint(4, 7))
            except:
                pass

        await asyncio.sleep(3)

        new_count_in_round = 0
        for container in current_containers:
            # 回退模式：容器本身就是 <a> 链接，直接提取 href
            tag_name = await container.evaluate('el => el.tagName.toLowerCase()') if hasattr(container, 'evaluate') else ''
            if tag_name == 'a':
                href = await container.get_attribute('href')
                if href:
                    v_link = _normalize_douyin_url(href)
                    if v_link not in captured_links:
                        captured_links.add(v_link)
                        # 尝试从父容器获取标题和作者信息
                        parent = await container.evaluate_handle('el => el.closest("div[class]") || el.parentElement')
                        title_text = ""
                        author_id = ""
                        try:
                            title_text = (await container.inner_text()).strip().replace('\n', ' ')[:200]
                        except Exception:
                            pass
                        results.append({
                            "Keyword": keyword,
                            "Author_ID": author_id,
                            "Title": title_text,
                            "Author_Home": "",
                            "Video_Link": v_link,
                            "Stats": 0,
                        })
                        new_count_in_round += 1
            else:
                data = await get_video_data(container, keyword)
                if data and data["Video_Link"] and data["Video_Link"] not in captured_links:
                    captured_links.add(data["Video_Link"])
                    results.append(data)
                    new_count_in_round += 1

        _log("info", f"📥 轮次 {i+1}: 新增 {new_count_in_round} 条 | 总计 {len(results)} 条")

        if max_items and len(results) >= max_items:
            results = results[:max_items]
            _log("info", f"✅ 已达到采集上限 {max_items} 条，停止滚动")
            break

        if new_count_in_round == 0:
            consecutive_zero_count += 1
            if consecutive_zero_count >= STUCK_THRESHOLD:
                _log("info", f"🛑 连续 {STUCK_THRESHOLD} 次未发现新内容，停止滚动。")
                break
        else:
            consecutive_zero_count = 0

    return results


async def main():
    KEYWORDS = ["高尔夫模拟器"]
    HEADLESS = False
    USER_DATA_DIR = "/Users/hyj/Documents/mywork/AutoMarketing/chrome_data/Chrome_Bot_Data_DY"

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=HEADLESS,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0]

        all_final_data = []
        for kw in KEYWORDS:
            try:
                data = await search_keywords(page, kw, max_items=5)
                all_final_data.extend(data)
                print(f"✅ '{kw}' 采集完成，当前累计 {len(all_final_data)} 条")
            except Exception as e:
                print(f"❌ 检索异常: {e}")
            await asyncio.sleep(random.randint(4, 7))

        if all_final_data:
            for item in all_final_data:
                print(f"📹 {item['Video_Link']}")
                print(f"   作者: {item['Author_ID']}")
                print(f"   标题: {item['Title']}")
                print(f"   播放量: {item['Stats']}")
                print()

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())