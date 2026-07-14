# scrape_reviews_v0.py 代码详解

## 文件概述

这是一个用于爬取 TikTok 视频评论的 Python 脚本。它具备智能反反爬机制，能够检测评论区空状态并自动重试，支持批量爬取多个视频的评论。

## 逐行代码解析

### 第一部分：导入模块（第 1-4 行）

```python
import asyncio
from playwright.async_api import async_playwright
import json, random
```

**解释：**
- `asyncio`: Python 异步编程库，用于处理并发任务
- `playwright.async_api`: Playwright 异步 API，用于浏览器自动化
- `json`: JSON 数据解析库
- `random`: 随机数生成库，用于模拟人类操作节奏

---

### 第二部分：全局配置（第 6-10 行）

```python
VIDEO_URL = "https://www.tiktok.com/@stastclkstocks/video/7641767208036896013"
```
**解释：** 默认测试视频 URL，用于单独调试

```python
MAX_SCROLLS = 10
```
**解释：** 每个视频最多滚动次数，用于加载更多评论

```python
MAX_RETRIES = 2
```
**解释：** 检测到空评论区时的最大重试次数

```python
REFRESH_EVERY = 10
```
**解释：** 每爬取 N 个视频后去首页刷一刷，重置会话状态，防止被限流

---

### 第三部分：拟人化浏览函数（第 13-30 行）

```python
async def _mimic_tiktok_feed(context):
    """去 TikTok 首页随机浏览，重置会话状态，防止评论区被限流"""
    page = await context.new_page()
```
**解释：**
- 定义异步函数 `_mimic_tiktok_feed`
- 创建新页面标签

```python
    try:
        print("📺 [拟人浏览] 前往 TikTok 首页刷新会话状态...")
        await page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=30000)
```
**解释：**
- 访问 TikTok "For You" 推荐页
- `wait_until="domcontentloaded"`: 等待 DOM 加载完成即可，不需要等待所有资源
- `timeout=30000`: 超时时间 30 秒

```python
        await asyncio.sleep(random.uniform(3, 6))
```
**解释：** 随机等待 3-6 秒，模拟人类阅读速度

```python
        for _ in range(random.randint(3, 6)):
            await page.mouse.wheel(0, random.randint(500, 1000))
            await asyncio.sleep(random.uniform(2, 4))
```
**解释：**
- 随机滚动 3-6 次
- `mouse.wheel(0, y)`: 模拟鼠标滚轮滚动，y 值为滚动距离
- 每次滚动后等待 2-4 秒

```python
            if random.random() < 0.2:
                await page.mouse.move(random.randint(200, 500), random.randint(200, 500))
```
**解释：** 20% 概率随机移动鼠标，增加拟人化效果

```python
        print("✅ [拟人浏览] 结束")
    except Exception as e:
        print(f"⚠️ [拟人浏览] 异常: {e}")
    finally:
        await page.close()
```
**解释：**
- 异常处理：捕获并打印异常
- `finally`: 无论成功失败都关闭页面

---

### 第四部分：空评论区检测函数（第 32-56 行）

```python
async def _is_comment_section_empty(page) -> bool:
    """
    检测评论区是否处于 "Start the conversation" 空状态。
    TikTok 限流或会话降级时会出现这个占位文案，但视频实际有评论。
    """
```
**解释：**
- 异步函数，返回布尔值
- 检测评论区是否显示空状态占位符

```python
    empty_indicators = [
        'p[data-e2e="comment-empty-text"]',
        'div[class*="DivEmptyContainer"]',
        'span:has-text("Start the conversation")',
        'span:has-text("Be the first to comment")',
    ]
```
**解释：** 定义空评论区的 CSS 选择器列表
- `data-e2e="comment-empty-text"`: TikTok 内部测试属性
- `DivEmptyContainer`: 空评论容器类名
- "Start the conversation": 空评论提示文案
- "Be the first to comment": 另一条空评论提示

```python
    for sel in empty_indicators:
        try:
            if await page.locator(sel).count() > 0:
                print(f"⚠️ 检测到评论区空状态占位符: {sel}")
                return True
        except Exception:
            pass
```
**解释：**
- 遍历所有空状态选择器
- `page.locator(sel)`: 定位元素
- `.count()`: 获取匹配元素数量
- 如果找到任何一个空状态标识，返回 True

```python
    # 兜底：等 3s 后仍然没有任何评论项，视为空
    try:
        await page.wait_for_selector('div[class*="DivCommentObjectWrapper"]', timeout=3000)
        return False
    except Exception:
        return True
```
**解释：**
- 兜底检测：等待 3 秒看是否出现评论项
- `DivCommentObjectWrapper`: 评论项容器类名
- 如果超时未出现评论，返回 True（空评论区）

---

### 第五部分：单视频评论爬取函数（第 58-140 行）

```python
async def scrape_comments(context, video_url, _retry=0):
    """
    爬取单个视频评论。
    遇到空评论区时自动重试（最多 MAX_RETRIES 次），
    重试前去首页拟人浏览以重置会话状态。
    """
    page = await context.new_page()
    await page.set_viewport_size({"width": 1280, "height": 800})
    print(f"🚀 正在打开 (retry={_retry}): {video_url}")
```
**解释：**
- `context`: Playwright 浏览器上下文
- `video_url`: 视频 URL
- `_retry`: 当前重试次数（内部参数）
- 设置视口大小为 1280x800

```python
    comments = []
    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
```
**解释：**
- 初始化评论列表
- 访问视频页面，超时 60 秒
- 等待 3 秒让页面完全加载

```python
        # 点击评论图标展开评论区
        comment_icon_btn = page.locator('button').filter(
            has=page.locator('span[data-e2e="comment-icon"]')
        )
        await comment_icon_btn.first.click()
        await page.wait_for_timeout(2000)
```
**解释：**
- 定位评论图标按钮
- `filter(has=...)`: 过滤包含评论图标的按钮
- `.first.click()`: 点击第一个匹配元素
- 等待 2 秒让评论区展开

```python
        item_selector = 'div[class*="DivCommentObjectWrapper"]'
        print("⏳ 等待评论项渲染...")
        try:
            await page.wait_for_selector(item_selector, timeout=10000)
        except Exception:
            pass  # 超时后继续走空状态检测
```
**解释：**
- 定义评论项选择器
- 等待评论项出现，最多 10 秒
- 超时不报错，继续后续检测

```python
        # ✅ 核心：检测空评论区 + 自动重试
        if await _is_comment_section_empty(page):
            await page.close()
            if _retry < MAX_RETRIES:
                wait_sec = random.randint(20, 40) * (_retry + 1)
                print(f"🔄 评论区为空（疑似限流），{wait_sec}s 后重试 ({_retry+1}/{MAX_RETRIES})...")
                await _mimic_tiktok_feed(context)
                await asyncio.sleep(wait_sec)
                return await scrape_comments(context, video_url, _retry=_retry + 1)
            else:
                print(f"❌ 重试 {MAX_RETRIES} 次后评论区仍为空，跳过该视频。")
                return comments
```
**解释：**
- 调用空评论区检测函数
- 如果为空且未达最大重试次数：
  - 计算等待时间：20-40 秒 × (重试次数+1)，递增等待
  - 调用拟人浏览函数重置会话
  - 等待后递归调用自身，重试次数+1
- 如果已达最大重试次数，返回空列表

```python
        prev_len = 0
        for i in range(MAX_SCROLLS):
            items = page.locator(item_selector)
            await items.first.wait_for(timeout=5000)
            current_count = await items.count()
```
**解释：**
- `prev_len`: 上一轮评论数量，用于检测是否触底
- 循环滚动加载评论
- 获取当前评论项数量

```python
            for j in range(current_count):
                try:
                    item = items.nth(j)
                    text_val = (await item.locator('span[data-e2e="comment-level-1"]').first.inner_text()).strip()
                    user_href = await item.locator('a[href*="/@"]').first.get_attribute('href')
                    uid = user_href.split('?')[0].split('/')[-1].replace('/@', '')
```
**解释：**
- 遍历所有评论项
- `items.nth(j)`: 获取第 j 个评论项
- 提取评论文本：定位 `data-e2e="comment-level-1"` 的 span
- 提取用户主页链接：定位包含 `/@` 的 a 标签
- 从链接中提取用户 ID：去除查询参数，提取最后一段，去掉 `@` 符号

```python
                    if not any(c['uid'] == uid and c['text'] == text_val for c in comments):
                        comments.append({
                            "uid": uid,
                            "user": uid,
                            "upage": f"https://www.tiktok.com/@{uid}",
                            "text": text_val
                        })
```
**解释：**
- 去重检查：如果评论已存在则跳过
- 添加评论到列表，包含：用户 ID、用户名、用户主页、评论内容

```python
                except Exception as e:
                    print(f"⚠️ 解析第 {j+1} 条评论时出错: {e}")
                    continue
```
**解释：** 异常处理，解析失败则跳过该评论

```python
            print(f"🔄 轮次 {i+1}: 捕获到 {len(comments)} 条评论")

            if current_count > 0:
                await items.nth(current_count - 1).scroll_into_view_if_needed()
                await page.wait_for_timeout(2000)
```
**解释：**
- 打印当前轮次评论数量
- 滚动到最后一个评论项，触发加载更多

```python
            if len(comments) == prev_len:
                print("✅ 确认触底，停止滚动")
                break

            prev_len = len(comments)
            await asyncio.sleep(random.randint(3, 8))
```
**解释：**
- 如果评论数量没有增加，说明已触底，停止滚动
- 更新上一轮评论数量
- 随机等待 3-8 秒

```python
    except Exception as e:
        print(f"❌ 整体运行报错: {e}")
    finally:
        await page.close()
        return comments
```
**解释：**
- 异常处理：捕获并打印异常
- `finally`: 无论成功失败都关闭页面并返回评论列表

---

### 第六部分：批量爬取函数（第 142-162 行）

```python
async def batch_scrape_comments(context, video_list):
    """
    批量爬取多个视频评论，供 run.py 调用。
    每 REFRESH_EVERY 个视频主动去首页刷新，防止会话降级导致评论区空白。
    """
    all_results = {}
```
**解释：**
- `context`: 浏览器上下文
- `video_list`: 视频 URL 列表
- 返回字典：`{视频URL: [评论列表]}`

```python
    for idx, video_url in enumerate(video_list):
        if idx > 0 and idx % REFRESH_EVERY == 0:
            print(f"\n🔄 已处理 {idx} 个视频，主动刷新会话状态...")
            await _mimic_tiktok_feed(context)
            sleep_sec = random.randint(30, 60)
            print(f"😴 休息 {sleep_sec}s...")
            await asyncio.sleep(sleep_sec)
```
**解释：**
- 遍历所有视频
- 每处理 `REFRESH_EVERY` 个视频（默认 10 个），主动刷新会话
- 调用拟人浏览函数
- 随机休息 30-60 秒

```python
        comments = await scrape_comments(context, video_url)
        all_results[video_url] = comments
        print(f"✅ [{idx+1}/{len(video_list)}] {video_url} → {len(comments)} 条评论\n")
        await asyncio.sleep(random.randint(10, 25))
```
**解释：**
- 调用单视频爬取函数
- 保存结果到字典
- 打印进度信息
- 随机等待 10-25 秒

```python
    return all_results
```
**解释：** 返回所有视频的评论映射

---

### 第七部分：主函数（第 164-177 行）

```python
async def main():
    USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data_TK1"
```
**解释：** 定义 Chrome 用户数据目录

```python
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
```
**解释：**
- 启动 Playwright
- 创建持久化浏览器上下文
- `channel="chrome"`: 使用 Chrome 浏览器
- `headless=False`: 显示浏览器窗口
- `no_viewport=True`: 不固定视口大小
- 禁用自动化检测特征

```python
        result = await scrape_comments(context, VIDEO_URL)
        print(f"\n🎉 共抓取评论数: {len(result)}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        await context.close()
```
**解释：**
- 调用单视频爬取函数
- 打印评论数量
- `json.dumps`: 格式化输出 JSON
  - `ensure_ascii=False`: 保留中文字符
  - `indent=2`: 缩进 2 空格
- 关闭浏览器上下文

---

### 第八部分：程序入口（第 179-183 行）

```python
if __name__ == "__main__":
    asyncio.run(main())
```
**解释：**
- Python 程序入口判断
- `asyncio.run(main())`: 运行异步主函数

---

## 程序运行流程

### 1. 初始化
- 配置全局参数（最大滚动次数、重试次数、刷新频率）

### 2. 单视频爬取流程
1. 打开视频页面
2. 点击评论图标展开评论区
3. 检测评论区是否为空状态
4. 如果为空，拟人浏览后重试（最多 2 次）
5. 循环滚动加载评论
6. 解析每条评论的用户 ID 和文本
7. 去重并保存

### 3. 批量爬取流程
1. 遍历视频列表
2. 每 10 个视频主动刷新会话
3. 调用单视频爬取函数
4. 保存结果到字典

---

## 如何运行此程序

### 前置条件

1. **安装依赖**
   ```bash
   pip install playwright
   playwright install chromium
   ```

2. **配置 Chrome 用户数据目录**
   修改 `USER_DATA_DIR` 为实际的 Chrome 数据目录

### 运行命令

```bash
# 直接运行（测试模式）
python src/TikTok/common/scrape_reviews_v0.py
```

### 在其他脚本中调用

```python
from scrape_reviews_v0 import scrape_comments, batch_scrape_comments

# 单视频爬取
comments = await scrape_comments(context, video_url)

# 批量爬取
all_comments = await batch_scrape_comments(context, video_urls)
```

---

## 关键技术点

### 1. 反反爬机制
- **拟人浏览**: 随机滚动、随机等待、随机鼠标移动
- **空状态检测**: 识别 TikTok 限流导致的假空评论区
- **自动重试**: 递增等待时间，最多重试 2 次
- **会话刷新**: 每 10 个视频主动刷新会话

### 2. 数据提取
- 使用 CSS 选择器精确定位评论元素
- 从用户主页链接中提取用户 ID
- 去重处理避免重复评论

### 3. 异步编程
- 使用 `async/await` 处理并发任务
- 提高网络请求效率

---

## 注意事项

1. **代理配置**: 需要配置代理服务器访问 TikTok
2. **登录状态**: 需要预先登录 TikTok 账号
3. **限流风险**: 频繁爬取可能触发 TikTok 限流
4. **选择器更新**: TikTok 页面结构可能变化，需要更新选择器

---

## 输出格式

### 单条评论数据结构

```json
{
  "uid": "username",
  "user": "username",
  "upage": "https://www.tiktok.com/@username",
  "text": "评论内容"
}
```

### 批量爬取返回格式

```python
{
  "https://www.tiktok.com/@user1/video/123": [
    {"uid": "commenter1", "text": "评论1"},
    {"uid": "commenter2", "text": "评论2"}
  ],
  "https://www.tiktok.com/@user2/video/456": [...]
}
```

---

## 常见问题

**Q1: 为什么评论区总是显示为空？**
A: 可能是被 TikTok 限流了。程序会自动重试，如果仍然失败，建议增加 `REFRESH_EVERY` 的间隔或延长等待时间。

**Q2: 如何提高爬取速度？**
A: 不建议过快爬取，容易触发反爬机制。可以适当减少 `MAX_SCROLLS` 或增加等待时间。

**Q3: 如何修改测试视频？**
A: 修改 `VIDEO_URL` 变量为目标视频链接。

**Q4: 为什么需要拟人浏览？**
A: TikTok 会检测异常行为，拟人浏览可以重置会话状态，降低被识别为机器人的风险。

---

## 总结

这是一个功能完善的 TikTok 评论爬取脚本，核心特点：

1. **智能反反爬**: 自动检测空评论区并重试
2. **拟人化操作**: 随机等待、随机滚动、随机鼠标移动
3. **批量处理**: 支持同时爬取多个视频
4. **会话管理**: 定期刷新会话防止限流

适用于自动化营销场景中的用户数据收集和分析。
