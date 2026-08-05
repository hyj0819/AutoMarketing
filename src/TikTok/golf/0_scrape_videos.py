import asyncio
import os, sys, json
import random
import time
import datetime
import csv

sys.path.append('src/TikTok/common')
from search_keywords_v0 import search_keywords
from scrape_reviews_v0 import scrape_comments, batch_scrape_comments
sys.path.append('src/utils')
from common_utils import get_adspower_ws, get_text_response_ds, load_contacted_users

sys.path.append('src')
from core.database import SessionLocal
from sqlalchemy import text
from core.security import decrypt_api_key

# ==================== 基础配置 ====================
PROJECT_NAME = "golf"
USER_DATA_DIR = "/Users/hyj/Documents/mywork/AutoMarketing/chrome_data/Chrome_Bot_Data_TK"
CONTACTED_USERS_FILE = f'files/TikTok/{PROJECT_NAME}/contacted_users.txt'
LOG_DIR = f"log/tiktok/{PROJECT_NAME}/{str(datetime.date.today())}"
TARGET_VIDEO_FILE = f"{LOG_DIR}/target_videos.txt"
TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
API_KEY_FILE = "conf/api_key.json"

USE_PERSONALIZED_MESSAGE = True
MAX_USERS = 5
EXCLUDE_AUTHOR = True

KEYWORDS = [
    "golf simulator",
    "indoor simulator",
    "launch monitor"
]

# golf 大V:
# https://www.tiktok.com/@golfsimrooms
# https://www.tiktok.com/@topgolf
# https://www.tiktok.com/@birdiesathleticclub

MESSAGES = []


async def verify_fingerprint(page):
    """验证浏览器指纹信息"""
    print("\n🔍 正在验证浏览器指纹...")
    try:
        await page.goto("https://browserleaks.com/js", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

        user_agent = await page.evaluate("navigator.userAgent")
        platform = await page.evaluate("navigator.platform")
        language = await page.evaluate("navigator.language")
        hardware_concurrency = await page.evaluate("navigator.hardwareConcurrency")
        device_memory = await page.evaluate("navigator.deviceMemory || 'N/A'")
        screen_resolution = await page.evaluate("screen.width + 'x' + screen.height")
        timezone = await page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")

        print("─────────────────────────────────────")
        print("📊 浏览器指纹信息:")
        print(f"  User-Agent: {user_agent[:80]}...")
        print(f"  Platform: {platform}")
        print(f"  Language: {language}")
        print(f"  CPU核心数: {hardware_concurrency}")
        print(f"  内存: {device_memory} GB")
        print(f"  屏幕分辨率: {screen_resolution}")
        print(f"  时区: {timezone}")
        print("─────────────────────────────────────")

        webdriver_detected = await page.evaluate("window.navigator.webdriver || false")
        if webdriver_detected:
            print("⚠️ 警告: 检测到 webdriver 属性，可能被网站识别为自动化工具")
        else:
            print("✅ webdriver 属性已隐藏")

        plugins_length = await page.evaluate("navigator.plugins.length")
        print(f"  插件数量: {plugins_length}")

        return {
            "user_agent": user_agent,
            "platform": platform,
            "webdriver_detected": webdriver_detected
        }
    except Exception as e:
        print(f"⚠️ 指纹验证失败: {e}")
        return None


async def open_tiktok_context(playwright, account_config: dict | None = None):
    """Open a local profile or attach to an already-running AdsPower profile."""
    browser_mode = os.environ.get("TIKTOK_BROWSER", "local").strip().lower()

    adspower_user_id = None
    account_name = None

    if account_config and account_config.get("browser_id"):
        adspower_user_id = account_config["browser_id"]
        account_name = account_config["account_name"]
        browser_mode = "adspower"
        print(f"✅ 已加载账号配置: {account_name}")

    if browser_mode == "adspower":
        if not adspower_user_id:
            adspower_user_id = os.environ.get("ADSPOWER_USER_ID", "").strip()
        if not adspower_user_id:
            raise RuntimeError("TIKTOK_BROWSER=adspower 时必须设置 ADSPOWER_USER_ID 或通过 account_id 指定")

        api_key = os.environ.get("ADSPOWER_API_KEY", "").strip()
        api_base_url = os.environ.get("ADSPOWER_API_BASE_URL", "http://127.0.0.1:50325")
        kwargs = {"base_url": api_base_url}
        if api_key:
            kwargs["api_key"] = api_key
        ws_endpoint = get_adspower_ws(adspower_user_id, **kwargs)
        if not ws_endpoint:
            raise RuntimeError("无法启动 AdsPower 档案，请确认 AdsPower 已启动、USER_ID 与 API Key 正确")

        browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
        if not browser.contexts:
            raise RuntimeError("AdsPower 已连接，但未返回可用浏览器上下文")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        print(f"✅ 已连接 AdsPower 档案: {adspower_user_id}")
        print(f"使用账号: {account_name or '未知'}; 指纹浏览器USER_ID: {adspower_user_id}")
        
        verify_fingerprint_enabled = os.environ.get("VERIFY_FINGERPRINT", "0") == "1"
        if verify_fingerprint_enabled:
            await verify_fingerprint(page)
            
        return context, page, True

    if browser_mode != "local":
        raise RuntimeError("TIKTOK_BROWSER 仅支持 local 或 adspower")

    context = await playwright.chromium.launch_persistent_context(
        USER_DATA_DIR,
        headless=os.environ.get("TIKTOK_HEADLESS", "0") == "1",
        no_viewport=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    print("✅ 已启动本地 TikTok 浏览器档案")
    
    verify_fingerprint_enabled = os.environ.get("VERIFY_FINGERPRINT", "0") == "1"
    if verify_fingerprint_enabled:
        await verify_fingerprint(page)
        
    return context, page, False


def load_prompt_by_business_line(business_line_code: str, template_code: str) -> str | None:
    """根据业务线编码和模板编码加载激活的提示词模板内容"""
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT pt.template_content FROM prompt_templates pt
                JOIN business_lines bl ON pt.business_line_id = bl.id
                WHERE bl.code = :business_line_code
                  AND pt.template_code = :template_code
                  AND pt.is_active = 1
                """
            ),
            {"business_line_code": business_line_code, "template_code": template_code},
        ).fetchone()
        return row.template_content if row else None
    finally:
        db.close()


def load_active_ai_model() -> dict | None:
    """从数据库获取激活的AI模型配置"""
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT api_key_encrypted, api_url FROM ai_models WHERE is_active = 1 LIMIT 1")
        ).fetchone()
        if not row:
            return None
        return {
            "api_key": decrypt_api_key(row.api_key_encrypted),
            "api_url": row.api_url
        }
    finally:
        db.close()


def load_account_by_id(account_id: int) -> dict | None:
    """从数据库获取账号配置"""
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT a.id, a.account_name, a.browser_id, p.name as platform_name
                FROM accounts a
                LEFT JOIN platforms p ON a.platform_id = p.id
                WHERE a.id = :account_id AND a.status = 1
            """),
            {"account_id": account_id}
        ).fetchone()
        if not row:
            return None
        return {
            "id": row.id,
            "account_name": row.account_name,
            "browser_id": row.browser_id,
            "platform_name": row.platform_name
        }
    finally:
        db.close()


async def main():
    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    all_potential_leads = []

    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)

    account_config = None
    account_id_env = os.environ.get("TIKTOK_ACCOUNT_ID", "").strip()
    if account_id_env:
        try:
            account_config = load_account_by_id(int(account_id_env))
            if not account_config:
                print(f"⚠️ 未找到账号ID {account_id_env} 或账号已禁用，将使用默认配置")
            elif not account_config.get("browser_id"):
                print(f"⚠️ 账号 [{account_config['account_name']}] 未配置浏览器ID，将使用本地模式")
        except ValueError:
            print(f"⚠️ TIKTOK_ACCOUNT_ID 值 '{account_id_env}' 不是有效的数字，将使用默认配置")

    ai_model_config = load_active_ai_model()
    if not ai_model_config or not ai_model_config["api_key"]:
        print(f"未找到激活的AI模型配置，请在后台管理系统中配置AI模型")
        exit(1)

    purchase_intent_prompt = load_prompt_by_business_line(PROJECT_NAME, "golf_purchase_intent")
    if not purchase_intent_prompt:
        print(f"未找到业务线 [{PROJECT_NAME}] 的购买意图分析提示词模板，将跳过 AI 筛选")
        ai_filter_enabled = False
    else:
        ai_filter_enabled = True

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        context, page, using_adspower = await open_tiktok_context(p, account_config)

        # --- 第一阶段：搜索视频 ---
        all_videos = []
        for kw in KEYWORDS:
            print(f"\n🔍 正在搜索关键词视频: {kw}")
            videos = await search_keywords(page, kw)
            all_videos.extend(videos)
            await asyncio.sleep(random.randint(1, 3))

        unique_videos = list({v['Video_Link']: v for v in all_videos if v['Video_Link']}.values())
        print(f"✅ 搜索完成，共获取 {len(unique_videos)} 个独立视频链接。")
        with open(TARGET_VIDEO_FILE, 'a') as fd:
            fd.writelines('\n'.join([x['Video_Link'] for x in unique_videos]))
            fd.writelines('\n')

        # --- 第二阶段：批量爬取评论（✅ 用 batch_scrape_comments，自动处理空评论区） ---
        video_urls = [v['Video_Link'] for v in unique_videos]
        video_meta = {v['Video_Link']: v for v in unique_videos}

        print(f"\n📦 开始批量爬取 {len(video_urls)} 个视频的评论...")
        all_comments_map = await batch_scrape_comments(context, video_urls)

        # --- 第三阶段：AI 筛选潜在客户 ---
        added_targets = []
        for v_url, comments in all_comments_map.items():
            v_title = video_meta[v_url].get('Title', '')
            v_author = video_meta[v_url].get('Author_ID', '')

            if not comments:
                print(f"⏭️ 跳过无评论视频: {v_url}")
                continue

            for c in comments:
                uid = c.get('uid')
                if (uid in contacted_users) or (uid in added_targets):
                    continue
                if EXCLUDE_AUTHOR and uid == v_author:
                    continue
                if not v_title.strip() or not c['text'].strip():
                    continue

                is_potential = True
                if ai_filter_enabled:
                    prompt = purchase_intent_prompt.replace("{{v_title}}", v_title).replace("{{comment_text}}", c["text"])
                    is_potential = get_text_response_ds(
                        "你是一个获客专家。请简洁判断。", prompt,
                        api_key=ai_model_config["api_key"],
                        base_url=ai_model_config["api_url"]
                    ).lower() == 'yes'

                if is_potential:
                    all_potential_leads.append({
                        "User_ID": uid,
                        "User_Page": c.get('upage'),
                        "Comment": c['text'],
                        "Source_Video": v_url,
                        "Source_Title": v_title
                    })
                    added_targets.append(uid)
                    print(f"🎯 发现目标用户: {uid}")

        # 去重
        all_potential_leads = list({u['User_ID']: u for u in all_potential_leads}.values())

        # --- 第四阶段：生成个性化文案并保存 ---
        print(f"\n🚀 开始生成文案，目标用户数: {len(all_potential_leads)}")
        potential_customer_data = [['uid', 'source url', 'source title', 'source comment', 'message']]

        for idx, lead in enumerate(all_potential_leads):
            target_id = lead["User_ID"]

            if USE_PERSONALIZED_MESSAGE:
                prompt = (
                    "【角色】\n"
                    "你是一位资深的高尔夫行业海外营销专家，擅长通过社交媒体（TikTok/Instagram/Reddit）进行精准截流获客。你的话术风格：专业、像圈内朋友、乐于助人、不生硬推销。\n\n"
                    "【背景】\n"
                    "我司经营高端室内高尔夫模拟器（Indoor Golf Simulator）。\n"
                    "产品核心优势：\n"
                    "1. 内置120+全国知名球场，1:1真实还原球场原貌。\n"
                    "2. 通过高清摄像头对球体和杆头进行动态实时捕捉，获得专业、精准的运动数据。\n"
                    "3. 以空气动力学算法为支撑，AI机器学习海量场外数据，实现运动轨迹智能精准预判。\n"
                    "4. 集成先进的physx物理引擎，高度模拟天气、风速、海拔等环境因素。\n"
                    "5. 内置智能电子球童，提供球场信息提示、线路辅助决策、障碍难点分析。\n\n"
                    "目标：根据用户评论生成个性化英文私信，吸引对方关注产品并建立联系。\n\n"
                    "【写作准则】\n"
                    "- 开场白：先用半句话带出原帖核心内容，再衔接用户评论，证明你真的读懂了。\n"
                    "- 禁止直接说“买我们的机器”，要用“我这里有解决方案/实拍视频，你想看看吗？”的方式。\n"
                    "- 每次选1-2个与评论场景最相关的产品优势自然嵌入，不要罗列全部卖点。\n"
                    "- 长度：严格控制在3-4句话，总字符数不超过350个。\n"
                    "- 语言：英文。整个私信前后不用加双引号。\n\n"
                    f"【帖子内容】：{lead['Source_Title']}\n\n"
                    f"【评论内容】：{lead['Comment']}"
                )
                message = get_text_response_ds("", prompt, api_key=ai_model_config["api_key"], base_url=ai_model_config["api_url"])
            else:
                message = random.choice(MESSAGES)

            print(f"({idx+1}/{len(all_potential_leads)}) {target_id}")
            print(f'📚 原贴: {lead["Source_Title"]}')
            print(f'💬 评论: {lead["Comment"]}')
            print(f'📝 文案: {message}\n')

            if message:
                potential_customer_data.append([
                    target_id,
                    lead['Source_Video'],
                    lead['Source_Title'],
                    lead['Comment'],
                    message
                ])

        with open(TARGET_USERS_FILE, 'w', newline='', encoding='utf-8') as file:
            csv.writer(file).writerows(potential_customer_data)

        print(f"\n💾 任务结束。潜在客户数据已保存至 {TARGET_USERS_FILE}")
        if using_adspower:
            print("AdsPower 档案保持运行，供后续任务复用。")
        else:
            await context.close()


if __name__ == "__main__":
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    start = time.time()
    asyncio.run(main())
    end = time.time()
    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    duration = end - start
    print(f"⏱️ 运行时长: {int(duration//3600):02d}:{int((duration%3600)//60):02d}:{duration%60:06.3f}")
