import asyncio
from openai import timeout
from playwright.async_api import async_playwright
from time import sleep
import random
import requests
import datetime
import sys, csv
from itertools import islice
sys.path.append('src/utils')
from common_utils import load_contacted_users, get_adspower_ws

"""
TikTok 评论回复模块
功能：点击评论下的回复按钮，输入回复内容并提交
"""


async def click_reply_button(page, comment_item, comment_index):
    """
    点击指定评论项的回复按钮
    
    Args:
        page: Playwright page对象
        comment_item: 评论容器元素
        comment_index: 评论索引（用于日志）
    
    Returns:
        bool: 是否成功点击回复按钮
    """
    try:
        # 定位回复按钮：p[data-e2e="comment-reply-1"]，role="button"
        reply_btn = await comment_item.query_selector('p[data-e2e="comment-reply-1"]')
        
        if not reply_btn:
            print(f"⚠️ 评论 #{comment_index} 未找到回复按钮")
            return False
        
        # 滚动到可见区域并点击
        await reply_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)
        await reply_btn.click()
        
        print(f"✅ 评论 #{comment_index} 的回复按钮已点击")
        await asyncio.sleep(1.5)  # 等待回复输入框展开
        return True
        
    except Exception as e:
        print(f"❌ 点击回复按钮失败 (评论 #{comment_index}): {e}")
        return False


async def input_reply_text(page, reply_text, comment_index):
    """
    在回复输入框中输入文本
    
    Args:
        page: Playwright page对象
        reply_text: 要输入的回复文本
        comment_index: 评论索引（用于日志）
    
    Returns:
        bool: 是否成功输入文本
    """
    try:
        # TikTok 回复框使用 Draft.js 富文本编辑器，结构为：
        #   div.DivReplyCommentEditorContainer
        #     -> div.public-DraftEditorPlaceholder-root  (placeholder，会拦截点击事件)
        #     -> div.DraftEditor-editorContainer
        #          -> div.public-DraftEditor-content[contenteditable="true"]  (真正的输入区)
        # 必须精确选中 .public-DraftEditor-content，不能用通用的 [contenteditable="true"]
        # 且不能用 .click()（placeholder 会拦截），改用 evaluate+focus 激活焦点
        input_selector = 'div.public-DraftEditor-content[contenteditable="true"]'
        
        # 等待回复框出现（回复按钮点击后需要一点时间展开）
        try:
            await page.wait_for_selector(input_selector, timeout=5000)
        except:
            print(f"⚠️ 评论 #{comment_index} 等待输入框超时")
            return False
        
        input_boxes = await page.query_selector_all(input_selector)
        
        if not input_boxes:
            print(f"⚠️ 评论 #{comment_index} 未找到输入框")
            return False
        
        # 使用最后一个输入框（最新打开的回复框）
        input_box = input_boxes[0]
        
        # 用 evaluate 直接 focus，绕过 placeholder 的点击拦截
        await page.evaluate("el => el.focus()", input_box)
        await asyncio.sleep(0.3)
        
        # Draft.js 不支持 fill()，用 keyboard.type() 逐字输入
        await page.keyboard.type(reply_text, delay=random.uniform(10, 50))
        
        print(f"✅ 评论 #{comment_index} 回复文本已输入: {reply_text[:50]}...")
        await asyncio.sleep(0.5)
        return True
        
    except Exception as e:
        print(f"❌ 输入回复文本失败 (评论 #{comment_index}): {e}")
        return False


async def submit_reply(page, comment_index):
    """
    提交回复内容
    
    Args:
        page: Playwright page对象
        comment_index: 评论索引（用于日志）
    
    Returns:
        bool: 是否成功提交
    """
    try:
        # 定位提交按钮：button[data-e2e="comment-post"]
        submit_btn = await page.query_selector('button[data-e2e="comment-post"]')
        
        if not submit_btn:
            # 备选选择器
            submit_btn = await page.query_selector('button[aria-label="Post"]')
        
        if not submit_btn:
            print(f"⚠️ 评论 #{comment_index} 未找到提交按钮")
            return False
        
        # 检查按钮是否禁用
        is_disabled = await submit_btn.get_attribute('disabled')
        if is_disabled:
            print(f"⚠️ 评论 #{comment_index} 提交按钮被禁用，可能内容为空")
            return False
        
        # 点击提交按钮
        await submit_btn.click()
        print(f"✅ 评论 #{comment_index} 回复已提交")
        
        await asyncio.sleep(2)  # 等待提交完成
        return True
        
    except Exception as e:
        print(f"❌ 提交回复失败 (评论 #{comment_index}): {e}")
        return False


async def reply_to_comment(page, comment_item, reply_text, comment_index):
    """
    完整的回复流程：点击回复 -> 输入文本 -> 提交
    
    Args:
        page: Playwright page对象
        comment_item: 评论容器元素
        reply_text: 回复内容
        comment_index: 评论索引
    
    Returns:
        bool: 是否成功回复
    """
    try:
        # 步骤 1：点击回复按钮
        if not await click_reply_button(page, comment_item, comment_index):
            return False
        
        # 步骤 2：输入回复文本
        if not await input_reply_text(page, reply_text, comment_index):
            # 尝试取消并关闭输入框
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except:
                pass
            return False
        
        # 步骤 3：提交回复
        if not await submit_reply(page, comment_index):
            # 尝试取消
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except:
                pass
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 回复评论失败 (评论 #{comment_index}): {e}")
        return False


async def extract_comment_data(page, comment_item, keyword):
    """
    从评论项提取数据
    
    Args:
        page: Playwright page对象
        comment_item: 评论容器元素
        keyword: 搜索关键词
    
    Returns:
        dict: 评论数据 {uid, user, upage, text}
    """
    try:
        # 提取用户ID
        user_a = await comment_item.query_selector('a[href*="/@"]')
        user_href = ""
        uid = ""
        if user_a:
            user_href = await user_a.get_attribute('href')
            if user_href:
                uid = user_href.split('?')[0].split('/')[-1].replace('/@', '')
        
        # 提取评论文本
        text_elem = await comment_item.query_selector('span[data-e2e="comment-level-1"]')
        text_val = ""
        if text_elem:
            text_val = (await text_elem.inner_text()).strip()
        
        return {
            "uid": uid,
            "user": uid,
            "upage": f"https://www.tiktok.com/@{uid}" if uid else "",
            "text": text_val
        }
    except Exception as e:
        print(f"⚠️ 解析评论数据出错: {e}")
        return None


async def reply_comments(page, idx, video_url, uid, comment_text, reply_text):
    """
    回复评论
    
    Args:
        page: Playwright page对象
        context: Playwright context对象（用于新页面）
        video_url: 视频URL
        comments_to_reply: 列表，每项为 {comment_text, reply_text, uid}
    
    Returns:
        list: 回复结果列表
    """
    results = []
    
    try:
        # 打开视频
        print(f"🚀 正在打开视频: {video_url}")
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(10000)
        
        # 点击评论图标展开评论区
        comment_icon_btn = page.locator('button').filter(
            has=page.locator('span[data-e2e="comment-icon"]')
        )
        try:
            await comment_icon_btn.first.click()
            await page.wait_for_timeout(2000)
        except:
            print("⚠️ 无法点击评论图标，继续尝试...")
        
        # 等待评论项加载
        item_selector = 'div[class*="DivCommentObjectWrapper"]'
        try:
            await page.wait_for_selector(item_selector, timeout=60000)
        except:
            print("⚠️ 评论项加载超时")
        

        try:
            print(f"  原评论: {comment_text}")
            print(f"  回复: {reply_text}")
            
            # 重新获取评论列表（每次刷新，确保DOM最新）
            await page.wait_for_selector(item_selector, timeout=30000)
            comment_items = await page.query_selector_all(item_selector)
            
            # 查找匹配的评论项
            target_item = None
            for item in comment_items:
                item_text = await item.query_selector('span[data-e2e="comment-level-1"]')
                if item_text:
                    item_text_content = (await item_text.inner_text()).strip()
                    print(f'item_text_content:{item_text_content}')
                    print(f'comment_text:{comment_text}')
                    if item_text_content == comment_text:
                        target_item = item
                        break
            
            if not target_item:
                print(f"  ⚠️ 未找到匹配的评论项")
                results.append({
                    'uid': uid,
                    'success': False,
                    'reason': '未找到匹配的评论'
                })

                return results
            
            # 执行回复
            success = await reply_to_comment(page, target_item, reply_text, idx + 1)
            
            results.append({
                'uid': uid,
                'success': success,
                'reason': '成功' if success else '失败'
            })
            
            # 冷却时间，防止限流
            await asyncio.sleep(random.randint(5, 10))
            
        except Exception as e:
            print(f"  ❌ 处理评论 #{idx+1} 出错: {e}")
            results.append({
                'uid': comments_to_reply[idx].get('uid', ''),
                'success': False,
                'reason': str(e)
            })
        
    except Exception as e:
        print(f"❌ 批量回复过程出错: {e}")
    
    return results




async def main():
    ADSPOWER_USER_ID = "k1byab0k" # "k1byab0k", "k1byap97"
    ACCOUNT_NAME = "NEAGLE_GOLF"

    PROJECT_NAME = "golf"
    LOG_DIR = f"log/tiktok/{PROJECT_NAME}/2026-06-12"
    TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers_reply.csv"
    REPLIED_COMMENTS_FILE = f'files/TikTok/{PROJECT_NAME}/replied_comments.txt'
    START_LINE_IDX = 1

    replied_comments = load_contacted_users(REPLIED_COMMENTS_FILE)
    print(f'使用账号:{ACCOUNT_NAME}; 指纹浏览器USER_ID:{ADSPOWER_USER_ID}\n')
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    print(f'Start from line {START_LINE_IDX} of {TARGET_USERS_FILE}\n')

    total_rows = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = list(csv.reader(file))
        total_rows = len(reader) - START_LINE_IDX

    sent_this_round = []
    success_cnt = 0
    with open(TARGET_USERS_FILE, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        
        async with async_playwright() as p:
            ws_endpoint = get_adspower_ws(ADSPOWER_USER_ID)
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                # commit 级别：只要开始接收数据就继续，不等待任何渲染
                await page.goto("https://whoer.net", wait_until="commit", timeout=10000)
            except Exception as e:
                print(f"⚠️ 导航触发提醒: {e}")

            for idx, (uid, v_url, v_text, v_comment, v_reply) in enumerate(islice(reader, START_LINE_IDX, None)):
                print(f"({idx+1}/{total_rows})")
                cur_token = f"{v_url};{uid};{v_comment}"
                if cur_token not in contacted_users:
                    try:
                        page_message = await context.new_page()
                        if v_reply.startswith('"') and msg.endswith('"'):
                            v_reply = v_reply[1:-1]
                        reply_ret = await reply_comments(page_message, idx, v_url, uid, v_comment, v_reply)
                        if reply_ret and reply_ret[0]['success']:
                            sent_this_round.append(uid)
                            replied_comments.add(cur_token)
                            # 严格冷却防止封号
                            #await asyncio.sleep(random.randint(5, 15))

                            success_cnt += 1

                            with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
                                f.writelines(f"{cur_token}\n")

                            if success_cnt >= MAX_USERS:
                                break

                            page_view = await context.new_page()
                            await mimic_human_behavior(page_view)
                            await page_view.close()

                            # 严格冷却防止封号（休息5~15分钟）
                            sleep_time = random.randint(8 * 60, 20 * 60)
                            print(f'睡眠{sleep_time}s')
                            await asyncio.sleep(sleep_time)

                        elif reply_ret and ('ERR_SOCKS_CONNECTION_FAILED' in reply_ret[0]['reason'] or 'ERR_CONNECTION_CLOSED' in reply_ret[0]['reason']):
                            print('🔗 网络连接失败，请检查网络！')
                            break

                    except Exception as e:
                        print(f"  ❌ 私信失败: {e}")
                    finally:
                        await page_message.close()
                else:
                    print(f'已经建联过用户{uid}，跳过！')

                print('\n\n')

    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    """
    if sent_this_round:
        with open(CONTACTED_USERS_FILE, 'a', encoding='utf-8') as f:
            for user in sent_this_round:
                f.write(f"{user}\n")
    """

    print(f"\n💾 任务结束。本轮成功发送 {len(sent_this_round)} 条私信。")


if __name__ == "__main__":
    asyncio.run(main())