# TikTok Golf 模块调试报告

**模块路径**: `/Users/hyj/Documents/mywork/AutoMarketing/src/TikTok/golf`  
**调试日期**: 2026-06-22  
**Python 版本**: 3.14.0  
**调试环境**: macOS

---

## 一、模块结构概览

```
src/TikTok/golf/
├── 0_scrape_videos.py      # 步骤0：搜索视频 + 爬取评论 + AI筛选潜在客户
├── 1_send_messages.py      # 步骤1：发送私信（含拟人化行为模拟）
├── 1_reply_comments.py     # 步骤1：回复评论（替代私信的互动方式）
├── chat_v0.py              # 私信发送核心逻辑（被其他模块调用）
└── run_auto_reply.py       # 自动回复完整流程（搜索+爬评论+AI判断+回复）
```

### 依赖关系图

```
0_scrape_videos.py
  ├── src/TikTok/common/search_keywords_v0.py   # 关键词搜索视频
  ├── src/TikTok/common/scrape_reviews_v0.py    # 爬取视频评论
  └── src/utils/common_utils.py                 # 公共工具函数

1_send_messages.py
  ├── src/utils/common_utils.py                 # 加载已触达用户、AdsPower
  └── chat_v0.py（未直接引用，但逻辑相关）

1_reply_comments.py
  └── src/utils/common_utils.py

run_auto_reply.py
  ├── src/TikTok/common/search_keywords_v0.py
  ├── src/TikTok/common/scrape_reviews_v0.py
  └── reply_comments_v0.py（❌ 文件不存在）
```

---

## 二、环境依赖检查

### 2.0 虚拟环境配置（已创建）

由于系统 Python 受 Homebrew 管理，已在项目根目录创建虚拟环境：

```bash
# 虚拟环境位置
.venv/

# 激活虚拟环境
source .venv/bin/activate

# 运行脚本（需先激活虚拟环境）
python3 src/TikTok/golf/0_scrape_videos.py
```

### 2.1 已安装依赖

| 包名 | 版本 | 状态 |
|------|------|------|
| playwright | 1.60.0 | ✅ 已安装 |
| openai | 2.43.0 | ✅ 已安装 |
| requests | 2.34.2 | ✅ 已安装 |
| pydantic | 2.13.4 | ✅ 已安装 |
| Pillow | 12.2.0 | ✅ 已安装 |
| pandas | 3.0.3 | ✅ 已安装 |
| openpyxl | 3.1.5 | ✅ 已安装 |
| python-dateutil | 2.9.0.post0 | ✅ 已安装 |
| pandas | 3.0.1 | ✅ 已安装 |
| python-dateutil | 2.9.0.post0 | ✅ 已安装 |

### 2.2 缺失依赖

| 包名 | 用途 | 影响模块 | 安装命令 |
|------|------|----------|----------|
| playwright | 浏览器自动化 | 所有模块 | `pip3 install playwright` |
| openai | DeepSeek API 调用 | 1_send_messages.py, 1_reply_comments.py | `pip3 install openai` |
| requests | HTTP 请求 | 1_send_messages.py, 1_reply_comments.py | `pip3 install requests` |
| pydantic | 数据验证 | 1_send_messages.py, chat_v0.py | `pip3 install pydantic` |
| Pillow | 图片处理 | common_utils.py | `pip3 install Pillow` |

### 2.3 Playwright 浏览器安装

```bash
# 安装 Playwright 后，还需安装浏览器
playwright install chromium
```

---

## 三、调试问题记录

### 问题 1：ModuleNotFoundError - playwright

**错误信息**:
```
ModuleNotFoundError: No module named 'playwright'
```

**影响模块**:
- `0_scrape_videos.py`
- `run_auto_reply.py`

**复现步骤**:
```bash
cd /Users/hyj/Documents/mywork/AutoMarketing
python3 src/TikTok/golf/0_scrape_videos.py
```

**根因分析**:
`playwright` 包未安装。该模块依赖 Playwright 进行浏览器自动化操作。

**解决方案**:
```bash
pip3 install playwright
playwright install chromium
```

---

### 问题 2：ModuleNotFoundError - openai

**错误信息**:
```
ModuleNotFoundError: No module named 'openai'
```

**影响模块**:
- `1_send_messages.py`
- `1_reply_comments.py`

**复现步骤**:
```bash
python3 src/TikTok/golf/1_send_messages.py
```

**根因分析**:
`openai` 包未安装。代码中使用 `from openai import timeout` 导入，但实际应该使用 `from openai import OpenAI`。

**解决方案**:
```bash
pip3 install openai
```

**代码问题**:
`1_send_messages.py` 和 `1_reply_comments.py` 第2行：
```python
from openai import timeout  # ❌ 错误的导入方式
```

应该改为：
```python
from openai import OpenAI  # ✅ 正确的导入方式
```

---

### 问题 3：路径解析问题（潜在问题）

**问题描述**:
所有模块使用相对路径添加 `sys.path`：
```python
sys.path.append('src/TikTok/common')
sys.path.append('src/utils')
```

**影响**:
- 必须在项目根目录 `/Users/hyj/Documents/mywork/AutoMarketing` 下执行
- 从其他目录执行会报 `ModuleNotFoundError`

**解决方案**:
使用基于 `__file__` 的绝对路径：
```python
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'utils')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'common')))
```

---

### 问题 4：run_auto_reply.py 引用不存在的模块

**错误信息**:
```python
from reply_comments_v0 import batch_reply_comments, extract_comment_data
```

**根因分析**:
`reply_comments_v0.py` 文件不存在。实际应该是 `1_reply_comments.py` 中的函数。

**解决方案**:
修改导入语句：
```python
# 从 1_reply_comments.py 导入
from importlib import util
spec = util.spec_from_file_location("reply_module", "src/TikTok/golf/1_reply_comments.py")
reply_module = util.module_from_spec(spec)
spec.loader.exec_module(reply_module)
```

或者将 `1_reply_comments.py` 中的函数提取到独立模块 `reply_comments_v0.py`。

---

### 问题 5：chat_v0.py 中 send_direct_message 函数设计问题

**问题描述**:
`chat_v0.py` 中的 `send_direct_message` 函数内部又调用 `async_playwright()`：

```python
async def send_direct_message(context, username, message_content):
    async with async_playwright() as p:  # ❌ 嵌套调用
        ...
```

**影响**:
- 函数参数 `context` 已经是从外部传入的浏览器上下文
- 内部再次创建 `async_playwright()` 会导致资源冲突
- 函数实际上不会使用传入的 `context`

**解决方案**:
移除内部的 `async_playwright()` 调用，直接使用传入的 `context`：

```python
async def send_direct_message(context, username, message_content):
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        # ... 原有逻辑
    finally:
        await page.close()
```

---

### 问题 6：代理端口配置错误

**错误信息**:
```
playwright._impl._errors.Error: Page.goto: net::ERR_PROXY_CONNECTION_FAILED
```

**根因分析**:
代码中硬编码了代理端口 `7890`，但系统实际代理端口是 `33210`。

**解决方案**:
修改 `0_scrape_videos.py` 第 61 行：
```python
proxy={"server": "http://127.0.0.1:33210"}
```

**检查系统代理端口**:
```bash
scutil --proxy | grep HTTPSPort
```

---

### 问题 7：TikTok 搜索页面返回空数据

**错误信息**:
```
⚠️ 轮次 1: 未检测到元素
   📥 轮次 1: 新增 0 条 | 总计 0 条
```

**根因分析**:
通过分析保存的 HTML 文件发现 `"vidList":[]`，说明 TikTok 搜索页面需要登录才能返回数据。页面被重定向到欧盟登录页面（`tiktok_web_login_static_eu`）。

**解决方案**:
1. 首次运行时需要手动登录 TikTok
2. 使用 `headless=False` 模式，在浏览器中完成登录
3. 登录状态会保存在 `USER_DATA_DIR` 指定的目录中

**登录步骤**:
```bash
# 1. 修改代码设置 headless=False（已设置）
# 2. 运行脚本
python3 src/TikTok/golf/0_scrape_videos.py

# 3. 在弹出的浏览器中手动登录 TikTok
# 4. 登录成功后，后续运行会自动使用保存的登录状态
```

---

### 问题 8：AdsPower 指纹浏览器未运行

**错误信息**:
```
❌ 请求 AdsPower API 出错: Expecting value: line 1 column 1 (char 0)
playwright._impl._errors.Error: BrowserType.connect_over_cdp: endpoint_url: expected string, got undefined
```

**影响模块**:
- `1_reply_comments.py`
- `1_send_messages.py`（部分功能）

**根因分析**:
代码依赖 AdsPower 指纹浏览器来管理多个 TikTok 账号，但 AdsPower 服务未启动（端口 50325 无响应）。

**解决方案**:
1. 启动 AdsPower 应用程序
2. 确保 AdsPower API 服务运行在 `http://127.0.0.1:50325`
3. 在 AdsPower 中创建浏览器配置文件，获取 `user_id`

**检查 AdsPower 状态**:
```bash
curl -s "http://127.0.0.1:50325/api/v1/browser/start?user_id=k1byab0k"
```

**替代方案**:
如果不使用 AdsPower，可以修改代码使用普通的 Playwright 浏览器上下文：
```python
# 替换 AdsPower CDP 连接
context = await p.chromium.launch_persistent_context(
    USER_DATA_DIR,
    headless=False,
    proxy={"server": "http://127.0.0.1:33210"}
)
```

---

### 问题 9：run_auto_reply.py 缺少模块

**错误信息**:
```
ModuleNotFoundError: No module named 'reply_comments_v0'
```

**根因分析**:
`run_auto_reply.py` 第 25 行导入了不存在的模块 `reply_comments_v0`：
```python
from reply_comments_v0 import batch_reply_comments, extract_comment_data
```

**解决方案**:
创建 `reply_comments_v0.py` 文件或修改导入语句。

**临时修复**（注释掉缺失的导入）:
```python
# 注释掉第 25 行
# from reply_comments_v0 import batch_reply_comments, extract_comment_data

# 或者从 1_reply_comments.py 导入（如果函数存在）
```

**建议**:
将 `1_reply_comments.py` 中的核心函数提取到独立的 `reply_comments_v0.py` 模块中。

---

### 问题 10：1_send_messages.py 缺少 import os

**错误信息**:
```
NameError: name 'os' is not defined
```

**根因分析**:
`1_send_messages.py` 第 13 行使用了 `os.path.join()`，但文件顶部没有导入 `os` 模块。

**解决方案**:
在 `1_send_messages.py` 文件顶部添加：
```python
import os
```

---

### 问题 11：TikTok 搜索页面 DOM 选择器失效

**错误信息**:
```
⚠️ 轮次 1: 未检测到元素
   📥 轮次 1: 新增 0 条 | 总计 0 条
```

**根因分析**:
TikTok 更新了页面结构，原有的 CSS 选择器 `div[class*="DivItemContainerV2"]` 不再匹配任何元素。通过分析保存的 HTML 文件发现，页面返回了空的视频列表（`"vidList":[]`）。

**解决方案**:
1. **更新选择器**：使用浏览器开发者工具检查 TikTok 搜索页面的实际 DOM 结构，找到新的视频卡片选择器
2. **使用更通用的选择器**：
   ```python
   # 尝试以下选择器
   ITEM_SELECTOR = 'div[data-e2e="search-card-item"]'
   # 或
   ITEM_SELECTOR = 'div[class*="VideoCard"]'
   # 或
   ITEM_SELECTOR = 'a[href*="/video/"]'  # 直接查找视频链接
   ```

**调试方法**:
```python
# 保存页面 HTML 用于分析
content = await page.content()
with open("/tmp/tiktok_search.html", "w", encoding="utf-8") as f:
    f.write(content)

# 在浏览器中打开并检查 DOM 结构
```

---

## 四、代码静态分析发现

### 4.1 硬编码路径问题

| 文件 | 行号 | 硬编码路径 | 建议 |
|------|------|-----------|------|
| 0_scrape_videos.py | 15 | `/Users/coast/Desktop/Chrome_Bot_Data_TK` | 使用配置文件或环境变量 |
| 1_send_messages.py | 12 | `/Users/coast/Desktop/chrome_profile` | 使用配置文件或环境变量 |
| chat_v0.py | 9 | `/Users/coast/Desktop/chrome_profile` | 使用配置文件或环境变量 |

### 4.2 配置建议

创建统一的配置文件 `conf/tiktok_config.json`：
```json
{
  "chrome_user_data_dir": "/Users/coast/Desktop/Chrome_Bot_Data_TK",
  "max_users": 5,
  "keywords": ["golf simulator", "indoor simulator", "launch monitor"],
  "messages": [
    "I saw your comment about the golf simulator. Are you looking for a home setup?",
    "Hey! I have some great indoor golf ideas if you're interested."
  ]
}
```

---

## 五、调试技巧总结

### 5.1 分步调试策略

1. **先测试导入**：
   ```bash
   python3 -c "import sys; sys.path.append('src/TikTok/common'); from search_keywords_v0 import search_keywords; print('✅ 导入成功')"
   ```

2. **小规模测试**：
   - 修改 `MAX_USERS = 1` 减少测试时间
   - 使用单个关键词测试搜索功能

3. **观察模式**：
   - 设置 `headless=False` 可以看到浏览器操作
   - 添加 `input("按回车继续...")` 进行断点调试

### 5.2 常见问题排查

| 问题 | 排查步骤 |
|------|----------|
| Chrome 未登录 | 手动运行 Chrome 登录 TikTok，检查用户数据目录 |
| API Key 错误 | 检查 `conf/api_key.json` 格式和内容 |
| 评论区为空 | TikTok 限流，等待一段时间或更换账号 |
| 私信发送失败 | 检查 TikTok 账号状态，是否被限制 |

### 5.3 性能优化建议

1. **批量处理评论**：
   - 使用 `batch_scrape_comments` 而不是逐个爬取
   - 自动处理空评论区，减少重试

2. **去重机制**：
   - 使用 `contacted_users.txt` 记录已触达用户
   - 在爬取阶段就过滤掉已触达用户

3. **拟人化行为**：
   - 随机滚动、随机停顿
   - 定期回首页刷会话状态，防止限流

---

## 六、最佳实践

### 6.1 代码组织

1. **统一路径处理**：
   ```python
   import os
   BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
   sys.path.insert(0, os.path.join(BASE_DIR, 'src', 'utils'))
   ```

2. **配置分离**：
   - 将硬编码路径移到配置文件
   - 使用环境变量管理敏感信息

3. **错误处理**：
   ```python
   try:
       # 业务逻辑
   except Exception as e:
       print(f"❌ 错误: {e}")
       # 记录日志
       # 可选：重试或跳过
   ```

### 6.2 反爬虫策略

1. **浏览器指纹**：
   ```python
   args=["--disable-blink-features=AutomationControlled"]
   ```

2. **拟人化操作**：
   - 随机延时
   - 模拟真实鼠标移动轨迹
   - 随机滚动和停顿

3. **会话管理**：
   - 定期回首页刷新
   - 避免短时间内大量请求
   - 使用多个账号轮换

### 6.3 数据管理

1. **去重文件**：
   - 使用 `contacted_users.txt` 记录已触达用户
   - 每行一个用户名，便于读写

2. **日志记录**：
   - 按日期创建日志目录
   - 记录目标视频、潜在客户、发送状态

3. **数据备份**：
   - 定期备份 `contacted_users.txt`
   - 保存爬取的评论数据

---

## 七、运行前检查清单

### 7.1 环境准备

- [ ] Python 3.8+ 已安装
- [ ] 所有依赖已安装：`playwright`, `openai`, `requests`, `pydantic`, `Pillow`
- [ ] Playwright 浏览器已安装：`playwright install chromium`

### 7.2 配置检查

- [ ] Chrome 用户数据目录存在且已登录 TikTok
- [ ] `conf/api_key.json` 包含有效的 DeepSeek API Key
- [ ] `files/TikTok/golf/contacted_users.txt` 文件存在（可为空）

### 7.3 代码检查

- [ ] 修复 `from openai import timeout` 为 `from openai import OpenAI`
- [ ] 修复 `run_auto_reply.py` 中不存在的模块引用
- [ ] 修复 `chat_v0.py` 中嵌套的 `async_playwright()` 调用

### 7.4 运行测试

```bash
# 在项目根目录执行
cd /Users/hyj/Documents/mywork/AutoMarketing

# 测试导入
python3 -c "import sys; sys.path.append('src/TikTok/common'); from search_keywords_v0 import search_keywords; print('✅ 导入成功')"

# 小规模测试
# 修改 0_scrape_videos.py 中的 MAX_USERS = 1
python3 src/TikTok/golf/0_scrape_videos.py
```

---

## 八、附录

### 8.1 依赖安装命令

```bash
# 一次性安装所有依赖
pip3 install playwright openai requests pydantic Pillow pandas openpyxl python-dateutil

# 安装 Playwright 浏览器
playwright install chromium
```

### 8.2 配置文件模板

**conf/api_key.json**:
```json
{
  "deepseek": {
    "api_key": "your-api-key-here"
  }
}
```

**conf/tiktok_config.json**（建议创建）:
```json
{
  "chrome_user_data_dir": "/Users/yourname/Desktop/Chrome_Bot_Data_TK",
  "max_users": 5,
  "keywords": ["golf simulator", "indoor simulator"],
  "messages": [
    "I saw your comment about the golf simulator. Are you looking for a home setup?"
  ]
}
```

### 8.3 调试命令参考

```bash
# 检查 Python 版本
python3 --version

# 检查已安装的包
pip3 list | grep -iE "playwright|openai|pandas"

# 测试模块导入
python3 -c "from playwright.async_api import async_playwright; print('✅ Playwright OK')"

# 运行单个模块
python3 src/TikTok/golf/0_scrape_videos.py
```

---

**文档版本**: v1.1  
**最后更新**: 2026-06-22  
**维护者**: AutoMarketing Team

---

## 九、调试总结（2026-06-22 实际运行）

### 9.1 已完成的修复

| 问题 | 修复状态 | 修复内容 |
|------|----------|----------|
| 依赖缺失 | ✅ 已修复 | 安装 playwright, openai, requests, pydantic, Pillow 等 |
| 虚拟环境 | ✅ 已创建 | 创建 `.venv/` 目录 |
| Playwright 浏览器 | ✅ 已安装 | 安装 Chromium 浏览器 |
| 硬编码路径 | ✅ 已修复 | 将 `/Users/coast/...` 改为相对路径 |
| 代理端口 | ✅ 已修复 | 从 `7890` 改为 `33210` |
| 缺少 import os | ✅ 已修复 | 在 `1_send_messages.py` 添加 `import os` |

### 9.2 待解决的问题

| 问题 | 严重程度 | 解决方案 |
|------|----------|----------|
| TikTok 未登录 | 🔴 阻断 | 首次运行需手动登录 TikTok，登录状态会保存在 `chrome_data/` 目录 |
| AdsPower 未运行 | 🔴 阻断 | 启动 AdsPower 应用程序，确保 API 服务在 `http://127.0.0.1:50325` 运行 |
| DOM 选择器失效 | 🟡 中等 | TikTok 更新了页面结构，需要更新 `search_keywords_v0.py` 中的选择器 |
| 缺少 reply_comments_v0 模块 | 🟡 中等 | 创建该文件或修改 `run_auto_reply.py` 的导入语句 |
| from openai import timeout | 🟡 中等 | 修改为 `from openai import OpenAI` |

### 9.3 各模块运行状态（2026-06-22 21:48-21:51 实际运行）

| 模块 | 运行状态 | 错误信息 | 备注 |
|------|----------|----------|------|
| 0_scrape_videos.py | ⚠️ 部分运行 | 搜索返回 0 个视频 | TikTok 未登录，页面返回空数据 |
| 1_send_messages.py | ❌ 失败 | AdsPower API 无响应 | 需要启动 AdsPower |
| 1_reply_comments.py | ❌ 失败 | AdsPower API 无响应 | 需要启动 AdsPower |
| run_auto_reply.py | ❌ 失败 | ModuleNotFoundError | 缺少 reply_comments_v0 模块 |

#### 详细运行日志

**0_scrape_videos.py 运行结果**:
```
Start at 2026-06-22 21:48:21

🔍 正在搜索关键词视频: golf simulator
🌐 正在检索关键词: golf simulator， 链接：https://www.tiktok.com/search/video?q=golf%20simulator
⚠️ 轮次 1: 未检测到元素
   📥 轮次 1: 新增 0 条 | 总计 0 条
⚠️ 轮次 2: 未检测到元素
   📥 轮次 2: 新增 0 条 | 总计 0 条
⚠️ 轮次 3: 未检测到元素
   📥 轮次 3: 新增 0 条 | 总计 0 条
   🛑 连续 3 次未发现新内容，停止滚动。

[其他关键词同样返回 0 个视频]

✅ 搜索完成，共获取 0 个独立视频链接。
📦 开始批量爬取 0 个视频的评论...
🚀 开始生成文案，目标用户数: 0
💾 任务结束。潜在客户数据已保存至 log/tiktok/golf/2026-06-22/potential_customers.csv
End at 2026-06-22 21:50:41
⏱️ 运行时长: 00:02:20.336
```

**1_send_messages.py 运行结果**:
```
使用账号:NEAGLE_GOLF; 指纹浏览器USER_ID:k1byab0k
Start at 2026-06-22 21:50:51
Start from line 236 of log/tiktok/golf/2026-06-12/potential_customers.csv
❌ 请求 AdsPower API 出错: Expecting value: line 1 column 1 (char 0)
Traceback (most recent call last):
  File "src/TikTok/golf/1_send_messages.py", line 280, in <module>
    asyncio.run(main())
  File "src/TikTok/golf/1_send_messages.py", line 214, in main
    browser = await p.chromium.connect_over_cdp(ws_endpoint)
playwright._impl._errors.Error: BrowserType.connect_over_cdp: endpoint_url: expected string, got undefined
```

**1_reply_comments.py 运行结果**:
```
使用账号:NEAGLE_GOLF; 指纹浏览器USER_ID:k1byab0k
Start at 2026-06-22 21:51:00
Start from line 1 of log/tiktok/golf/2026-06-12/potential_customers_reply.csv
❌ 请求 AdsPower API 出错: Expecting value: line 1 column 1 (char 0)
Traceback (most recent call last):
  File "src/TikTok/golf/1_reply_comments.py", line 423, in <module>
    asyncio.run(main())
  File "src/TikTok/golf/1_reply_comments.py", line 356, in main
    browser = await p.chromium.connect_over_cdp(ws_endpoint)
playwright._impl._errors.Error: BrowserType.connect_over_cdp: endpoint_url: expected string, got undefined
```

**run_auto_reply.py 运行结果**:
```
Traceback (most recent call last):
  File "src/TikTok/golf/run_auto_reply.py", line 25, in <module>
    from reply_comments_v0 import batch_reply_comments, extract_comment_data
ModuleNotFoundError: No module named 'reply_comments_v0'
```

### 9.4 后续操作建议

#### 优先级 1：登录 TikTok
```bash
# 1. 激活虚拟环境
source .venv/bin/activate

# 2. 运行脚本（会弹出浏览器）
python3 src/TikTok/golf/0_scrape_videos.py

# 3. 在浏览器中手动登录 TikTok
# 4. 登录成功后，后续运行会自动使用保存的登录状态
```

#### 优先级 2：启动 AdsPower（如使用多账号）
```bash
# 1. 启动 AdsPower 应用程序
# 2. 确保 API 服务运行在 http://127.0.0.1:50325
# 3. 检查 AdsPower 状态
curl -s "http://127.0.0.1:50325/api/v1/browser/start?user_id=k1byab0k"
```

#### 优先级 3：更新 DOM 选择器
```python
# 在 search_keywords_v0.py 中更新选择器
# 使用浏览器开发者工具检查 TikTok 搜索页面的实际 DOM 结构

# 尝试以下选择器：
ITEM_SELECTOR = 'div[data-e2e="search-card-item"]'
# 或
ITEM_SELECTOR = 'div[class*="VideoCard"]'
# 或
ITEM_SELECTOR = 'a[href*="/video/"]'  # 直接查找视频链接
```

#### 优先级 4：修复代码问题
```python
# 1. 修复 openai 导入
# 在 1_send_messages.py 和 1_reply_comments.py 中：
from openai import OpenAI  # 替换 from openai import timeout

# 2. 修复 run_auto_reply.py 的导入
# 注释掉第 25 行或创建 reply_comments_v0.py 文件
```

### 9.5 调试技巧

1. **检查代理状态**：
   ```bash
   scutil --proxy | grep HTTPSPort
   ```

2. **检查 AdsPower 状态**：
   ```bash
   curl -s "http://127.0.0.1:50325/api/v1/browser/start?user_id=k1byab0k"
   ```

3. **保存页面 HTML 用于调试**：
   ```python
   content = await page.content()
   with open("/tmp/tiktok_search.html", "w", encoding="utf-8") as f:
       f.write(content)
   ```

4. **使用 headless=False 观察浏览器行为**：
   ```python
   context = await p.chromium.launch_persistent_context(
       USER_DATA_DIR,
       headless=False,  # 显示浏览器窗口
       proxy={"server": "http://127.0.0.1:33210"}
   )
   ```

---

**文档版本**: v1.1  
**最后更新**: 2026-06-22  
**维护者**: AutoMarketing Team
