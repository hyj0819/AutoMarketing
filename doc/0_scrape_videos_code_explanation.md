# 0_scrape_videos.py 代码详解

## 文件概述

这是一个用于从 TikTok 自动抓取视频、分析评论并筛选潜在客户的 Python 脚本。主要用于高尔夫行业的自动化营销获客。

## 逐行代码解析

### 第一部分：导入模块（第 1-11 行）

```python
import asyncio
import os, sys, json
import random
import time
import datetime
import csv
```

**解释：**
- `asyncio`: Python 异步编程库，用于处理并发任务
- `os`: 操作系统接口，用于文件和目录操作
- `sys`: 系统相关功能，用于修改 Python 路径
- `json`: JSON 数据解析库
- `random`: 随机数生成库
- `time`: 时间处理库
- `datetime`: 日期时间处理库
- `csv`: CSV 文件读写库

```python
sys.path.append('src/TikTok/common')
from search_keywords_v0 import search_keywords
from scrape_reviews_v0 import scrape_comments, batch_scrape_comments
```

**解释：**
- `sys.path.append()`: 将 `src/TikTok/common` 目录添加到 Python 模块搜索路径
- `from search_keywords_v0 import search_keywords`: 导入关键词搜索函数
- `from scrape_reviews_v0 import scrape_comments, batch_scrape_comments`: 导入评论抓取函数
  - `scrape_comments`: 单个视频评论抓取
  - `batch_scrape_comments`: 批量视频评论抓取（新版优化）

```python
sys.path.append('src/utils')
from common_utils import get_text_response_ds, load_contacted_users
```

**解释：**
- 添加 `src/utils` 到模块搜索路径
- `get_text_response_ds`: 调用 DeepSeek AI 接口获取文本响应
- `load_contacted_users`: 加载已联系用户列表，避免重复联系

---

### 第二部分：基础配置（第 13-35 行）

```python
PROJECT_NAME = "golf"
```
**解释：** 定义项目名称为 "golf"，用于生成文件路径

```python
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "chrome_data", "Chrome_Bot_Data_TK")
```
**解释：** 
- 构建 Chrome 浏览器用户数据目录的绝对路径
- 从当前文件向上追溯 4 层目录，然后拼接 `chrome_data/Chrome_Bot_Data_TK`
- 用于保存浏览器会话状态（Cookie、登录信息等）

```python
os.makedirs(USER_DATA_DIR, exist_ok=True)
```
**解释：** 创建目录，如果目录已存在则不报错

```python
CONTACTED_USERS_FILE = f'files/TikTok/{PROJECT_NAME}/contacted_users.txt'
```
**解释：** 已联系用户文件路径，用于记录已发送消息的用户 ID

```python
LOG_DIR = f"log/tiktok/{PROJECT_NAME}/{str(datetime.date.today())}"
```
**解释：** 日志目录路径，按日期分类，例如：`log/tiktok/golf/2026-06-22`

```python
TARGET_VIDEO_FILE = f"{LOG_DIR}/target_videos.txt"
```
**解释：** 目标视频链接保存文件

```python
TARGET_USERS_FILE = f"{LOG_DIR}/potential_customers.csv"
```
**解释：** 潜在客户数据保存文件（CSV 格式）

```python
API_KEY_FILE = "conf/api_key.json"
```
**解释：** DeepSeek API 密钥配置文件路径

```python
USE_PERSONALIZED_MESSAGE = True
```
**解释：** 是否使用 AI 生成个性化消息（True=使用，False=使用预设模板）

```python
MAX_USERS = 5
```
**解释：** 最大处理用户数（当前代码中未实际使用此限制）

```python
EXCLUDE_AUTHOR = True
```
**解释：** 是否排除视频作者本人（避免给视频创作者发消息）

```python
KEYWORDS = [
    "golf simulator",
    "indoor simulator",
    "launch monitor"
]
```
**解释：** TikTok 搜索关键词列表
- "golf simulator": 高尔夫模拟器
- "indoor simulator": 室内模拟器
- "launch monitor": 发球监测器

```python
MESSAGES = []
```
**解释：** 预设消息模板列表（当前为空，因为启用了个性化消息）

---

### 第三部分：主函数定义（第 38-40 行）

```python
async def main():
    contacted_users = load_contacted_users(CONTACTED_USERS_FILE)
    all_potential_leads = []
```

**解释：**
- `async def main()`: 定义异步主函数
- `contacted_users`: 加载已联系过的用户 ID 集合，避免重复联系
- `all_potential_leads`: 存储所有潜在客户的列表

```python
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)
```
**解释：** 如果日志目录不存在，则创建它

```python
    api_keys = json.load(open(API_KEY_FILE))
    if "deepseek" not in api_keys or "api_key" not in api_keys["deepseek"]:
        print(f"deepseek api key not found in {API_KEY_FILE}")
        exit(1)
```
**解释：**
- 加载 API 密钥配置文件（JSON 格式）
- 检查是否包含 DeepSeek 的 API 密钥
- 如果缺失，打印错误信息并退出程序（退出码 1）

---

### 第四部分：启动浏览器（第 42-52 行）

```python
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
```
**解释：**
- 导入 Playwright 异步 API
- `async_playwright()`: 创建 Playwright 异步上下文管理器
- Playwright 是一个浏览器自动化工具，用于模拟真实用户操作

```python
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
            proxy={"server": "http://127.0.0.1:33210"}
        )
```
**解释：**
- 启动 Chromium 浏览器的持久化上下文（保留登录状态）
- `USER_DATA_DIR`: 浏览器数据保存目录
- `headless=False`: 显示浏览器窗口（False=显示，True=隐藏）
- `no_viewport=True`: 不固定视口大小，使用默认窗口尺寸
- `args=["--disable-blink-features=AutomationControlled"]`: 禁用自动化检测特征，防止被网站识别为机器人
- `proxy={"server": "http://127.0.0.1:33210"}`: 使用本地代理服务器（端口 33210），用于翻墙访问 TikTok

```python
        page = context.pages[0]
```
**解释：** 获取浏览器的第一个页面标签

---

### 第五部分：第一阶段 - 搜索视频（第 54-65 行）

```python
        # --- 第一阶段：搜索视频 ---
        all_videos = []
        for kw in KEYWORDS:
            print(f"\n🔍 正在搜索关键词视频: {kw}")
            videos = await search_keywords(page, kw)
            all_videos.extend(videos)
            await asyncio.sleep(random.randint(1, 3))
```
**解释：**
- 遍历所有关键词
- `search_keywords(page, kw)`: 调用搜索函数，在 TikTok 上搜索指定关键词的视频
- `all_videos.extend(videos)`: 将搜索结果添加到视频列表
- `await asyncio.sleep(random.randint(1, 3))`: 随机等待 1-3 秒，模拟人类操作节奏，防止被反爬

```python
        unique_videos = list({v['Video_Link']: v for v in all_videos if v['Video_Link']}.values())
```
**解释：**
- 去重：使用字典键的唯一性去除重复视频
- `v['Video_Link']`: 以视频链接作为键
- `if v['Video_Link']`: 过滤掉空链接
- 最终得到独立视频列表

```python
        print(f"✅ 搜索完成，共获取 {len(unique_videos)} 个独立视频链接。")
        with open(TARGET_VIDEO_FILE, 'a') as fd:
            fd.writelines('\n'.join([x['Video_Link'] for x in unique_videos]))
            fd.writelines('\n')
```
**解释：**
- 打印搜索结果数量
- 以追加模式（'a'）打开视频文件
- 将所有视频链接写入文件，每行一个链接
- 最后添加一个换行符

---

### 第六部分：第二阶段 - 批量爬取评论（第 67-71 行）

```python
        # --- 第二阶段：批量爬取评论（✅ 用 batch_scrape_comments，自动处理空评论区） ---
        video_urls = [v['Video_Link'] for v in unique_videos]
        video_meta = {v['Video_Link']: v for v in unique_videos}
```
**解释：**
- `video_urls`: 提取所有视频链接列表
- `video_meta`: 创建视频元数据字典，以链接为键，方便后续查找

```python
        print(f"\n📦 开始批量爬取 {len(video_urls)} 个视频的评论...")
        all_comments_map = await batch_scrape_comments(context, video_urls)
```
**解释：**
- `batch_scrape_comments`: 批量抓取所有视频的评论
- 返回一个字典：`{视频链接: [评论列表]}`
- 每个评论包含：`uid`（用户 ID）、`text`（评论内容）、`upage`（用户主页）等

---

### 第七部分：第三阶段 - AI 筛选潜在客户（第 73-118 行）

```python
        # --- 第三阶段：AI 筛选潜在客户 ---
        added_targets = []
        for v_url, comments in all_comments_map.items():
```
**解释：**
- `added_targets`: 记录已添加的目标用户，避免同一用户被多次添加
- 遍历每个视频及其评论

```python
            v_title = video_meta[v_url].get('Title', '')
            v_author = video_meta[v_url].get('Author_ID', '')
```
**解释：**
- 获取视频标题和作者 ID
- `.get()`: 安全获取字典值，如果键不存在返回默认值

```python
            if not comments:
                print(f"⏭️ 跳过无评论视频: {v_url}")
                continue
```
**解释：** 如果视频没有评论，跳过该视频

```python
            for c in comments:
                uid = c.get('uid')
                if (uid in contacted_users) or (uid in added_targets):
                    continue
                if EXCLUDE_AUTHOR and uid == v_author:
                    continue
                if not v_title.strip() or not c['text'].strip():
                    continue
```
**解释：**
- 遍历每条评论
- `uid`: 评论用户的 ID
- 检查用户是否已联系过或已添加，如果是则跳过
- 如果启用 `EXCLUDE_AUTHOR` 且用户是视频作者，跳过
- 如果视频标题或评论内容为空，跳过

```python
                prompt = (
                    "【角色】\n"
                    "你是一位拥有 10 年经验的高尔夫行业资深市场分析师，擅长通过社交媒体的碎片化信息捕捉用户的购买信号（Buying Signals）。\n\n"
                    "【任务】\n"
                    "我将为你提供 TikTok 视频的【标题内容】和用户的【评论内容】。请你分析该用户是否有购买室内高尔夫模拟器的潜在意图。\n\n"
                    "【判定维度】\n"
                    "请基于以下几个维度进行判断（判断标准需要严格一些，得要有比较明确的购买信号）：\n"
                    "1、用户是否在咨询购买意见/寻求推荐。\n"
                    "2、用户是否在抱怨现有设备的问题，或表达了具体的环境限制（如天气、空间）。\n"
                    "3、用户是否询问了关于价格、品牌、参数、安装或软件兼容性的问题。\n"
                    "4、用户是否提到了自己的家庭环境（如车库、地下室、办公室）。\n"
                    "5、用户是否表达了强烈的羡慕或"我也想要一套"的愿望。\n\n"
                    "【输出格式】\n"
                    "请直接输出yes或者no，不需要其他说明。\n\n"
                    f"【标题内容】: {v_title}\n\n"
                    f"【评论内容】: {c['text']}"
                )
```
**解释：**
- 构建 AI 提示词（Prompt）
- 定义 AI 角色：高尔夫行业市场分析师
- 任务：分析用户是否有购买意图
- 5 个判定维度：
  1. 咨询购买意见
  2. 抱怨现有设备或表达环境限制
  3. 询问价格、品牌、参数等
  4. 提到家庭环境
  5. 表达强烈愿望
- 要求 AI 只输出 "yes" 或 "no"
- 动态插入视频标题和评论内容

```python
                is_potential = get_text_response_ds(
                    "你是一个获客专家。请简洁判断。", prompt,
                    api_key=api_keys["deepseek"]["api_key"]
                )
```
**解释：**
- 调用 DeepSeek AI 接口
- 第一个参数：系统提示（System Prompt）
- 第二个参数：用户提示（User Prompt）
- 传入 API 密钥
- 返回 "yes" 或 "no"

```python
                if is_potential.lower() == 'yes':
                    all_potential_leads.append({
                        "User_ID": uid,
                        "User_Page": c.get('upage'),
                        "Comment": c['text'],
                        "Source_Video": v_url,
                        "Source_Title": v_title
                    })
                    added_targets.append(uid)
                    print(f"🎯 发现目标用户: {uid}")
```
**解释：**
- 如果 AI 判断为 "yes"，将用户添加到潜在客户列表
- 保存用户信息：ID、主页链接、评论内容、来源视频、视频标题
- 将用户 ID 添加到已添加列表
- 打印发现目标用户的提示

---

### 第八部分：去重处理（第 120-121 行）

```python
        # 去重
        all_potential_leads = list({u['User_ID']: u for u in all_potential_leads}.values())
```
**解释：**
- 再次去重，确保同一用户只出现一次
- 使用字典键的唯一性，以 User_ID 为键

---

### 第九部分：第四阶段 - 生成个性化文案（第 123-173 行）

```python
        # --- 第四阶段：生成个性化文案并保存 ---
        print(f"\n🚀 开始生成文案，目标用户数: {len(all_potential_leads)}")
        potential_customer_data = [['uid', 'source url', 'source title', 'source comment', 'message']]
```
**解释：**
- 打印目标用户数量
- 初始化 CSV 数据表头：用户 ID、来源 URL、来源标题、评论内容、生成的消息

```python
        for idx, lead in enumerate(all_potential_leads):
            target_id = lead["User_ID"]
```
**解释：**
- 遍历所有潜在客户
- `enumerate`: 同时获取索引和数据
- `target_id`: 当前处理的用户 ID

```python
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
                    "- 禁止直接说"买我们的机器"，要用"我这里有解决方案/实拍视频，你想看看吗？"的方式。\n"
                    "- 每次选1-2个与评论场景最相关的产品优势自然嵌入，不要罗列全部卖点。\n"
                    "- 长度：严格控制在3-4句话，总字符数不超过350个。\n"
                    "- 语言：英文。整个私信前后不用加双引号。\n\n"
                    f"【帖子内容】：{lead['Source_Title']}\n\n"
                    f"【评论内容】：{lead['Comment']}"
                )
                message = get_text_response_ds("", prompt, api_key=api_keys["deepseek"]["api_key"])
```
**解释：**
- 如果启用个性化消息，构建 AI 提示词
- 定义 AI 角色：高尔夫行业海外营销专家
- 介绍产品背景：5 个核心优势
- 写作准则：
  - 开场白要自然衔接原帖和评论
  - 禁止直接推销
  - 选择 1-2 个相关优势
  - 控制在 3-4 句话，350 字符内
  - 使用英文
- 调用 AI 生成消息

```python
            else:
                message = random.choice(MESSAGES)
```
**解释：** 如果不使用个性化消息，从预设模板中随机选择

```python
            print(f"({idx+1}/{len(all_potential_leads)}) {target_id}")
            print(f'📚 原贴: {lead["Source_Title"]}')
            print(f'💬 评论: {lead["Comment"]}')
            print(f'📝 文案: {message}\n')
```
**解释：** 打印处理进度和详细信息

```python
            if message:
                potential_customer_data.append([
                    target_id,
                    lead['Source_Video'],
                    lead['Source_Title'],
                    lead['Comment'],
                    message
                ])
```
**解释：** 如果生成了消息，将数据添加到 CSV 数据列表

```python
        with open(TARGET_USERS_FILE, 'w', newline='', encoding='utf-8') as file:
            csv.writer(file).writerows(potential_customer_data)
```
**解释：**
- 以写入模式（'w'）打开 CSV 文件
- `newline=''`: 避免 Windows 系统出现空行
- `encoding='utf-8'`: 使用 UTF-8 编码，支持中文
- `csv.writer(file).writerows()`: 将所有数据写入 CSV 文件

```python
        print(f"\n💾 任务结束。潜在客户数据已保存至 {TARGET_USERS_FILE}")
        await context.close()
```
**解释：**
- 打印任务完成提示
- 关闭浏览器上下文

---

### 第十部分：程序入口（第 176-182 行）

```python
if __name__ == "__main__":
    print(f'Start at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    start = time.time()
    asyncio.run(main())
    end = time.time()
    print(f'End at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    duration = end - start
    print(f"⏱️ 运行时长: {int(duration//3600):02d}:{int((duration%3600)//60):02d}:{duration%60:06.3f}")
```

**解释：**
- `if __name__ == "__main__":`: Python 程序入口判断，确保只有直接运行此文件时才执行
- 打印开始时间（格式：年-月-日 时:分:秒）
- `start = time.time()`: 记录开始时间戳
- `asyncio.run(main())`: 运行异步主函数
- `end = time.time()`: 记录结束时间戳
- 计算并打印运行时长（格式：时:分:秒.毫秒）

---

## 程序运行流程

### 1. 准备工作
- 加载已联系用户列表
- 检查 API 密钥配置
- 创建日志目录

### 2. 启动浏览器
- 使用 Playwright 启动 Chromium 浏览器
- 配置代理服务器（用于翻墙）
- 加载浏览器持久化数据（保留登录状态）

### 3. 第一阶段：搜索视频
- 遍历关键词列表
- 调用 `search_keywords` 函数搜索 TikTok 视频
- 去重并保存视频链接

### 4. 第二阶段：爬取评论
- 调用 `batch_scrape_comments` 批量抓取所有视频的评论
- 返回视频链接到评论列表的映射

### 5. 第三阶段：AI 筛选潜在客户
- 遍历每个视频的每条评论
- 构建提示词，调用 DeepSeek AI 判断用户是否有购买意图
- 将判断为 "yes" 的用户添加到潜在客户列表

### 6. 第四阶段：生成个性化文案
- 遍历所有潜在客户
- 根据用户评论和产品优势，调用 AI 生成个性化英文私信
- 将所有数据保存到 CSV 文件

### 7. 结束
- 关闭浏览器
- 打印运行时长

---

## 如何运行此程序

### 前置条件

1. **安装 Python 3.8+**
   ```bash
   python --version  # 检查 Python 版本
   ```

2. **安装依赖包**
   ```bash
   pip install playwright
   playwright install chromium
   ```

3. **配置 API 密钥**
   创建 `conf/api_key.json` 文件：
   ```json
   {
     "deepseek": {
       "api_key": "your_deepseek_api_key_here"
     }
   }
   ```

4. **配置代理服务器**
   确保本地代理服务器运行在 `127.0.0.1:33210`（用于访问 TikTok）

5. **准备依赖模块**
   确保以下文件存在：
   - `src/TikTok/common/search_keywords_v0.py`
   - `src/TikTok/common/scrape_reviews_v0.py`
   - `src/utils/common_utils.py`

### 运行命令

```bash
# 在项目根目录下执行
python src/TikTok/golf/0_scrape_videos.py
```

### 输出文件

1. **视频链接文件**
   - 路径：`log/tiktok/golf/YYYY-MM-DD/target_videos.txt`
   - 内容：所有搜索到的视频链接

2. **潜在客户文件**
   - 路径：`log/tiktok/golf/YYYY-MM-DD/potential_customers.csv`
   - 内容：CSV 格式，包含用户 ID、来源视频、评论内容、生成的消息

### 运行示例输出

```
Start at 2026-06-22 10:30:00

🔍 正在搜索关键词视频: golf simulator
✅ 搜索完成，共获取 25 个独立视频链接。

📦 开始批量爬取 25 个视频的评论...

⏭️ 跳过无评论视频: https://www.tiktok.com/@user/video/123
🎯 发现目标用户: @golfer123
🎯 发现目标用户: @golf_fan456

🚀 开始生成文案，目标用户数: 2
(1/2) @golfer123
📚 原贴: Best indoor golf simulator review
💬 评论: Where can I buy this?
📝 文案: Hey! Saw you're interested in indoor simulators. We have a premium setup with 120+ courses and pro-level tracking. Want to see a demo video?

(2/2) @golf_fan456
📚 原贴: Golf simulator setup guide
💬 评论: My garage is too small for this
📝 文案: Noticed you mentioned space constraints. Our compact simulator fits perfectly in garages and basements. Check out this installation video!

💾 任务结束。潜在客户数据已保存至 log/tiktok/golf/2026-06-22/potential_customers.csv

End at 2026-06-22 11:15:30

⏱️ 运行时长: 00:45:30.123
```

---

## 关键技术点

### 1. 异步编程（asyncio）
- 使用 `async/await` 语法处理并发任务
- 提高网络请求效率

### 2. 浏览器自动化（Playwright）
- 模拟真实用户操作
- 支持持久化登录状态
- 配置代理防止被封禁

### 3. AI 集成（DeepSeek）
- 使用 AI 判断用户购买意图
- 生成个性化营销消息

### 4. 数据处理
- 使用字典去重
- CSV 文件读写
- 字符串格式化

---

## 注意事项

1. **反爬虫机制**
   - 随机延迟（1-3 秒）模拟人类操作
   - 禁用自动化检测特征
   - 使用代理服务器

2. **API 成本**
   - 每次 AI 调用都会消耗 API 额度
   - 建议先小规模测试

3. **合规性**
   - 遵守 TikTok 服务条款
   - 避免过度频繁请求
   - 尊重用户隐私

4. **错误处理**
   - 当前代码缺少完善的异常处理
   - 建议添加 try-except 块处理网络错误

---

## 常见问题

**Q1: 为什么需要代理服务器？**
A: TikTok 在国内无法访问，需要通过代理服务器翻墙。

**Q2: 如何修改搜索关键词？**
A: 修改 `KEYWORDS` 列表，添加你感兴趣的关键词。

**Q3: 如何禁用个性化消息？**
A: 将 `USE_PERSONALIZED_MESSAGE` 设置为 `False`，并在 `MESSAGES` 列表中添加预设模板。

**Q4: 运行失败提示 API 密钥错误？**
A: 检查 `conf/api_key.json` 文件是否存在，格式是否正确。

**Q5: 如何查看已联系的用户？**
A: 查看 `files/TikTok/golf/contacted_users.txt` 文件。

---

## 总结

这是一个完整的 TikTok 自动化营销脚本，通过以下步骤实现精准获客：

1. **搜索** → 按关键词搜索相关视频
2. **抓取** → 批量获取视频评论
3. **筛选** → AI 判断潜在购买意图
4. **生成** → 创建个性化营销消息
5. **保存** → 导出客户数据到 CSV

整个流程高度自动化，结合了浏览器自动化、AI 分析和数据处理技术，是一个典型的现代 Python 自动化应用案例。
