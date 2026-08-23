"""
抖音爬虫任务 Pipeline（写库版）

将原独立脚本的逻辑改造为：
- 可传参（任务配置来自 task_executions.task_config）
- 写数据库（contents / contacts / contact_interactions）
- 实时回写进度与日志（通过 TaskContext）
- 步骤间支持停止检测（ctx.is_cancelled）
"""

import asyncio
import json
import os
import sys

from sqlalchemy import text

from src.core.database import SessionLocal
from src.worker import config

_PROJECT_ROOT = config.PROJECT_ROOT
sys.path.append(str(_PROJECT_ROOT / "src" / "Douyin" / "common"))
sys.path.append(str(_PROJECT_ROOT / "src" / "utils"))

from search_keywords_douyin import search_keywords  # noqa: E402
from scrape_reviews_douyin import batch_scrape_comments  # noqa: E402
from common_utils import get_text_response_ds, get_adspower_ws  # noqa: E402


def _extract_content_id(video_url: str) -> str:
    try:
        if "/video/" in video_url:
            return video_url.split("/video/")[-1].split("?")[0].strip("/")
    except Exception:
        pass
    return video_url


def _load_business_context(business_line_id: int) -> tuple[int, int]:
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT platform_id FROM business_lines WHERE id = :id"),
            {"id": business_line_id},
        ).fetchone()
        if not row:
            raise ValueError(f"业务线 {business_line_id} 不存在")
        return row.platform_id, business_line_id
    finally:
        db.close()


def _load_prompt_template(template_id: int | None) -> str | None:
    if not template_id:
        return None
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT template_content FROM prompt_templates WHERE id = :id"),
            {"id": template_id},
        ).fetchone()
        return row.template_content if row else None
    finally:
        db.close()


def _load_prompt_by_business_line(business_line_id: int, template_code: str) -> str | None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT template_content FROM prompt_templates
                WHERE business_line_id = :business_line_id
                  AND template_code = :template_code
                  AND is_active = 1
                """
            ),
            {"business_line_id": business_line_id, "template_code": template_code},
        ).fetchone()
        return row.template_content if row else None
    finally:
        db.close()


def _save_content(platform_id: int, business_line_id: int, video: dict, keyword: str):
    db = SessionLocal()
    try:
        content_id = _extract_content_id(video.get("Video_Link", ""))
        db.execute(
            text(
                """
                INSERT OR IGNORE INTO contents
                    (platform_id, business_line_id, content_type, content_id, content_url,
                     title, author_id, author_name, engagement_stats, source_keyword)
                VALUES
                    (:pid, :blid, 'video', :cid, :url, :title, :author, :author, :stats, :kw)
                """
            ),
            {
                "pid": platform_id,
                "blid": business_line_id,
                "cid": content_id,
                "url": video.get("Video_Link", ""),
                "title": video.get("Title", ""),
                "author": video.get("Author_ID", ""),
                "stats": json.dumps({"views": video.get("Stats", 0)}, ensure_ascii=False),
                "kw": keyword,
            },
        )
        db.commit()
    except Exception as e:
        print(f"⚠️ 写入视频失败: {e}")
        db.rollback()
    finally:
        db.close()


def _save_contact(
    platform_id: int,
    business_line_id: int,
    task_id: int,
    uid: str,
    profile_url: str,
    metadata: dict,
) -> bool:
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                """
                INSERT OR IGNORE INTO contacts
                    (platform_id, business_line_id, platform_user_id, username, profile_url,
                     contact_status, metadata)
                VALUES
                    (:pid, :blid, :uid, :uid, :url, 'pending', :meta)
                """
            ),
            {
                "pid": platform_id,
                "blid": business_line_id,
                "uid": uid,
                "url": profile_url,
                "meta": json.dumps(metadata, ensure_ascii=False),
            },
        )
        inserted = result.rowcount > 0
        crow = db.execute(
            text("SELECT id FROM contacts WHERE platform_id = :pid AND platform_user_id = :uid"),
            {"pid": platform_id, "uid": uid},
        ).fetchone()
        if crow:
            db.execute(
                text(
                    """
                    INSERT INTO contact_interactions
                        (contact_id, interaction_type, task_execution_id, detail)
                    VALUES (:cid, 'scraped', :tid, :detail)
                    """
                ),
                {
                    "cid": crow.id,
                    "tid": task_id,
                    "detail": json.dumps(metadata, ensure_ascii=False),
                },
            )
        db.commit()
        return inserted
    except Exception as e:
        print(f"⚠️ 写入潜在客户失败: {e}")
        db.rollback()
        return False
    finally:
        db.close()


async def run_scrape(task: dict, ctx):
    task_id = task["id"]
    cfg = json.loads(task.get("task_config") or "{}")
    keywords = cfg.get("keywords", [])
    max_items = cfg.get("max_items_per_keyword", 50)
    content_types = cfg.get("content_types") or ["video", "comment"]
    max_comments_per_video = cfg.get("max_comments_per_video", 0)
    timeout_seconds = cfg.get("timeout_seconds", 60)
    timeout_ms = timeout_seconds * 1000
    ai_filter_enabled = cfg.get("ai_filter_enabled", True)
    ai_prompt_template_id = cfg.get("ai_prompt_template_id")
    exclude_author = cfg.get("exclude_author", True)

    scrape_comments_enabled = "comment" in content_types

    if not keywords:
        raise ValueError("任务配置缺少 keywords")

    platform_id, business_line_id = _load_business_context(task["business_line_id"])

    prompt_template = None
    if ai_filter_enabled:
        if ai_prompt_template_id:
            prompt_template = _load_prompt_template(ai_prompt_template_id)
        if not prompt_template:
            prompt_template = _load_prompt_by_business_line(business_line_id, "douyin_purchase_intent")
    if ai_filter_enabled and not prompt_template:
        ctx.log("warn", f"未找到提示词模板，将跳过 AI 筛选")
        ai_filter_enabled = False

    deepseek_key = config.get_deepseek_api_key() if ai_filter_enabled else ""

    account_id = task.get("account_id")
    account_config = None
    if account_id:
        account_config = config.load_account_config(account_id)

    profile_dir = config.resolve_chrome_profile(task.get("bl_config"), task.get("platform_code"))
    headless = config.is_headless()

    use_adspower = False
    adspower_user_id = None
    account_name = None

    if account_config and account_config.get("browser_id"):
        use_adspower = True
        adspower_user_id = account_config["browser_id"]
        account_name = account_config["account_name"]
        ctx.log("info", f"✅ 已加载账号配置: {account_name}")
        ctx.log("info", f"任务启动，打开指纹浏览器（user_id={adspower_user_id}, headless={headless}）")
    else:
        ctx.log("info", f"任务启动，打开浏览器（profile={profile_dir}, headless={headless}）")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        if use_adspower:
            api_key = os.environ.get("ADSPOWER_API_KEY", "").strip()
            api_base_url = os.environ.get("ADSPOWER_API_BASE_URL", "http://127.0.0.1:50325")
            kwargs = {"base_url": api_base_url}
            if api_key:
                kwargs["api_key"] = api_key

            ctx.log("info", f"尝试连接 AdsPower（user_id={adspower_user_id}, base_url={api_base_url}）")
            ws_endpoint = get_adspower_ws(adspower_user_id, **kwargs)

            if not ws_endpoint:
                ctx.log("warning", "AdsPower 连接失败，自动降级为本地浏览器模式")
                ctx.log("info", f"降级到本地模式: profile={profile_dir}, headless={headless}")

                context = await p.chromium.launch_persistent_context(
                    profile_dir,
                    channel="chrome",
                    headless=headless,
                    no_viewport=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = context.pages[0] if context.pages else await context.new_page()
                use_adspower = False
            else:
                browser = await p.chromium.connect_over_cdp(ws_endpoint)
                if not browser.contexts:
                    ctx.log("warning", "AdsPower 已连接，但未返回可用浏览器上下文，降级为本地模式")
                    context = await p.chromium.launch_persistent_context(
                        profile_dir,
                        channel="chrome",
                        headless=headless,
                        no_viewport=True,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    page = context.pages[0] if context.pages else await context.new_page()
                    use_adspower = False
                else:
                    context = browser.contexts[0]
                    page = context.pages[0] if context.pages else await context.new_page()
                    ctx.log("info", f"✅ 已连接 AdsPower 档案: {adspower_user_id}")
        else:
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                channel="chrome",
                headless=headless,
                no_viewport=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()

        try:
            all_videos = []
            for kw in keywords:
                if ctx.is_cancelled():
                    ctx.log("warn", "检测到停止信号，中断搜索阶段")
                    await context.close()
                    return
                ctx.log("info", f"开始搜索关键词: {kw}")
                try:
                    videos = await search_keywords(page, kw, max_items=max_items, log_fn=ctx.log)
                except Exception as e:
                    ctx.log("error", f"关键词 [{kw}] 搜索失败: {e}")
                    videos = []
                for v in videos:
                    v["_keyword"] = kw
                    _save_content(platform_id, business_line_id, v, kw)
                all_videos.extend(videos)
                ctx.log("info", f"关键词 [{kw}] 搜索完成，获取 {len(videos)} 个视频")
                await asyncio.sleep(1)

            unique_videos = list(
                {v["Video_Link"]: v for v in all_videos if v.get("Video_Link")}.values()
            )
            video_meta = {v["Video_Link"]: v for v in unique_videos}
            video_urls = [v["Video_Link"] for v in unique_videos]

            if not scrape_comments_enabled:
                ctx.log("info", f"搜索阶段完成，共 {len(video_urls)} 个独立视频")
                ctx.log("info", "内容类型未含评论，仅采集视频列表，跳过评论与AI分析")
                ctx.update_progress(total=len(video_urls), success=len(video_urls), pending=0, progress=100)
                return

            ctx.log("info", f"搜索阶段完成，共 {len(video_urls)} 个独立视频，开始爬取评论")

            if ctx.is_cancelled():
                ctx.log("warn", "检测到停止信号，中断于评论阶段前")
                await context.close()
                return

            ctx.log("info", f"评论爬取超时设置: {timeout_seconds}秒")
            all_comments_map = await batch_scrape_comments(
                context, video_urls,
                max_comments_per_video=(max_comments_per_video or None),
                log_fn=ctx.log,
                timeout_ms=timeout_ms
            )

            pending_comments = []
            seen = set()
            for v_url, comments in all_comments_map.items():
                v_meta = video_meta.get(v_url, {})
                v_title = v_meta.get("Title", "")
                v_author = v_meta.get("Author_ID", "")
                v_keyword = v_meta.get("_keyword", "")
                for c in comments:
                    uid = c.get("uid")
                    if not uid or uid in seen:
                        continue
                    if exclude_author and uid == v_author:
                        continue
                    if not v_title.strip() or not c.get("text", "").strip():
                        continue
                    seen.add(uid)
                    pending_comments.append(
                        {
                            "uid": uid,
                            "upage": c.get("upage", f"https://www.douyin.com/user/{uid}"),
                            "text": c["text"],
                            "video_url": v_url,
                            "title": v_title,
                            "keyword": v_keyword,
                        }
                    )

            total = len(pending_comments)
            ctx.update_progress(total=total, success=0, failed=0, pending=total, progress=0)
            ctx.log("info", f"评论爬取完成，共 {total} 条待分析评论")

            success = 0
            failed = 0
            leads = 0
            for idx, item in enumerate(pending_comments):
                if ctx.is_cancelled():
                    ctx.log("warn", "检测到停止信号，中断分析阶段")
                    await context.close()
                    return

                is_potential = True
                if ai_filter_enabled:
                    prompt = prompt_template.replace("{{v_title}}", item["title"]).replace("{{comment_text}}", item["text"])
                    try:
                        answer = await asyncio.to_thread(
                            get_text_response_ds,
                            "你是一个获客专家。请简洁判断。",
                            prompt,
                            "deepseek-v4-flash",
                            deepseek_key,
                        )
                        is_potential = (answer or "").strip().lower().startswith("yes")
                    except Exception as e:
                        failed += 1
                        ctx.log("error", f"评论分析异常({item['uid']}): {e}")
                        _update_counters(ctx, total, success, failed)
                        continue

                success += 1
                if is_potential:
                    metadata = {
                        "comment": item["text"],
                        "source_video": item["video_url"],
                        "source_title": item["title"],
                        "source_keyword": item["keyword"],
                    }
                    if _save_contact(
                        platform_id,
                        business_line_id,
                        task_id,
                        item["uid"],
                        item["upage"],
                        metadata,
                    ):
                        leads += 1
                        ctx.log("info", f"🎯 发现潜在客户: {item['uid']}")

                _update_counters(ctx, total, success, failed)

                if total and (idx + 1) % 10 == 0:
                    ctx.log("info", f"分析进度: {idx + 1}/{total}，累计潜在客户 {leads}")

            ctx.log(
                "info",
                f"分析完成：已分析 {success} 条，异常 {failed} 条，命中潜在客户 {leads} 个",
            )
            ctx.update_progress(progress=100, pending=0)
        finally:
            try:
                if not use_adspower:
                    await context.close()
                else:
                    ctx.log("info", "AdsPower 档案保持运行，供后续任务复用。")
            except Exception:
                pass


def _update_counters(ctx, total: int, success: int, failed: int):
    done = success + failed
    pending = max(total - done, 0)
    progress = int(done / total * 100) if total else 0
    ctx.update_progress(success=success, failed=failed, pending=pending, progress=progress)