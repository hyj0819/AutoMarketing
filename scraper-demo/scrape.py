#!/usr/bin/env python3
"""
TikTok 评论爬虫 - Python 版本
用法: python3 scrape.py <video_url> [cookie_file]
"""

print("=== scrape.py 开始执行 ===", flush=True)  # 添加这行

import asyncio
import json
import re
import sys
from playwright.async_api import async_playwright
from openai import OpenAI
import datetime
import pytz  # 需要安装：pip install pytz
import sys
import os

def get_cookies_from_file(cookie_file):
    try:
        with open(cookie_file, 'r') as f:
            return f.read().strip()
    except:
        pass
    return None


TEXT_CLIENT = OpenAI(api_key="sk-604786760f5f4e6a9a233b1e7cf397f2", base_url="https://api.deepseek.com/v1")

def get_text_response_ds(context, prompt, model='deepseek-chat'):
    title_response = TEXT_CLIENT.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": context},
            {"role": "user", "content": prompt},
        ],
        stream=False
    )
    response_content = title_response.choices[0].message.content #.replace('\n', '<br>')
    
    return response_content

async def scrape_comments(video_url, cookie_file=''):
    cookies_string = get_cookies_from_file(cookie_file)
    # 或者也支持环境变量作为备选
    if not cookies_string:
        cookies_string = os.environ.get('TIKTOK_COOKIES', '')
    # ... 其余代码不变 ...
    
    # 提取视频 ID
    match = re.search(r'/video/(\d+)', video_url)
    if not match:
        print(json.dumps({"success": False, "message": "无法解析视频ID"}))
        return
    video_id = match.group(1)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="en-US"
        )

        if cookies_string:
            # 解析 Cookie
            cookies = []
            pairs = cookies_string.split(';')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.strip().split('=', 1)
                    cookies.append({
                        'name': key.strip(),
                        'value': value.strip(),
                        'domain': '.tiktok.com',
                        'path': '/',
                        'secure': True,
                        'httpOnly': False
                    })
            await context.add_cookies(cookies)

        page = await context.new_page()
        comments = []
        seen = set()

        # 监听评论接口
        async def handle_response(response):
            try:
                url = response.url
                if "comment" not in url or video_id not in url:
                    return

                data = await response.json()
                if isinstance(data, dict) and "comments" in data:
                    print(f"Found {len(data['comments'])} comments in API response", file=sys.stderr)
                    
                    for c in data.get("comments", []):
                        cid = c.get("cid")
                        if not cid or cid in seen:
                            continue
                        
                        seen.add(cid)
                        user = c.get("user", {})
                        
                        comment = {
                            "cid": cid,
                            "text": c.get("text") or c.get("comment_description", ""),
                            "user": user.get("nickname") or user.get("unique_id", "unknown"),
                            "uid": user.get("unique_id") or user.get("user_id", "unknown"),
                            "upage": f"https://www.tiktok.com/@{user.get('unique_id', 'unknown')}",
                            "likes": c.get("digg_count", 0),
                            "reply_count": c.get("reply_comment_total", 0),
                            'create_time': c.get("create_time", "")
                        }
                        comments.append(comment)
                        
            except Exception as e:
                print(f"Response parse error: {e}", file=sys.stderr)

        page.on("response", handle_response)

        print(f"Opening {video_url}...", file=sys.stderr)
        await page.goto(video_url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)

        # 点击评论按钮
        try:
            await page.click('span[data-e2e="comment-icon"]', timeout=5000)
            print("Clicked comment icon", file=sys.stderr)
        except:
            try:
                await page.click('[data-e2e="browse-comment"]', timeout=5000)
                print("Clicked browse-comment", file=sys.stderr)
            except:
                print("Could not find comment button", file=sys.stderr)

        await page.wait_for_timeout(2000)

        # 滚动加载评论
        prev_count = 0
        for i in range(50):
            try:
                items = page.locator('div[class*="DivCommentObjectWrapper"]')
                count = await items.count()
                
                if count > prev_count:
                    last_item = items.nth(count - 1)
                    await last_item.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1500)
                    prev_count = count
                    print(f"Scroll {i}, loaded {count} comments", file=sys.stderr)
                else:
                    break
            except:
                break

        await browser.close()
        
        return comments

async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "message": "Usage: python3 scrape.py <video_url> [cookie_file]"}))
        return

    video_url = sys.argv[1]
    
    # 从文件读取 Cookie
    cookies_string = None
    if len(sys.argv) >= 3:
        cookie_file = sys.argv[2]
        try:
            with open(cookie_file, 'r') as f:
                cookies_string = f.read().strip()
        except Exception as e:
            print(f"Failed to read cookie file: {e}", file=sys.stderr)
    
    try:
        comments = await scrape_comments(video_url, cookies_string)  # 传入 cookies_string
                
        '''
        # 输出 JSON 结果
        reviewers = [
            {
                "reviewer": c["user"],
                "reviewerUid": c["uid"],
                "reviewerPage": c["upage"],
                "content": c["text"],
                "likes": c["likes"],
                "platform": "TikTok"
            }
            for c in comments
        ]
        '''

        reviewerContents = [c['text'] for c in comments]

        ret = get_text_response_ds(f"你是一个很有经验的分析师",
                                    f"请帮我分析一下以下{len(reviewerContents)}条评论内容，并判断每个评论内容是否表达了评论者的购买意愿（yes表示是，no表示否；评判标准不用很严格）。评论内容：{reviewerContents}，列表中每个元素都表示一条评论。要求：1、只返回判断结果，不需要其他信息；2、返回一个列表，列表中每个元素是字符串（'yes'或'no'），长度和输入的评论内容列表长度一致。举例：评论内容是：['I want one', 'hahah'], 那么判断结果应该是['yes', 'no']",
                                    model='deepseek-chat')
        ret = [item.strip() for item in ret.strip('[]').replace("'", "").split(',')]

        reviewers = [{"reviewer": c['user'],
                      "reviewerUid": c['uid'], 
                      "reviewerPage": c['upage'],
                      "reviewContent": c['text'],
                      "reviewTime":  datetime.datetime.fromtimestamp(int(c['create_time']), tz=pytz.UTC).strftime('%Y-%m-%d %H:%M:%S'),
                      "platform": "TikTok"
                    }
                    for c, r in zip(comments, ret)
                    if r == 'yes']

        #print(f'reviewers:{reviewers}')
        result = {
            "success": True,
            "message": f"获取到 {len(reviewers)} 条评论",
            "data": {
                "reviewers": reviewers,
                "totalComments": len(reviewers)
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        
    except Exception as e:
        print(json.dumps({"success": False, "message": str(e)}), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
