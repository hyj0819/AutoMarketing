# AutoMarketing 项目结构说明文档

## 一、项目概述

AutoMarketing 是一个基于 Python + Playwright 的社交媒体自动化营销系统，主要功能包括：
- 多平台内容爬取（评论、帖子、视频信息）
- AI 驱动的潜在客户意图识别（基于 DeepSeek 大模型）
- 自动化私信触达（模拟真人行为）
- 多账号管理（支持 AdsPower 指纹浏览器）

支持平台：Reddit、TikTok、Twitter/X、TradingView、Facebook、Instagram、Pinterest、YouTube、小红书。

---

## 二、目录层级结构

```
AutoMarketing/
├── conf/                          # 配置文件目录
│   └── api_key.json               # API 密钥配置（DeepSeek）
├── doc/                           # 项目文档目录
│   └── project_structure.md       # 本文档
├── files/                         # 运行时数据文件
│   ├── Reddit/                    # Reddit 已触达用户记录
│   │   ├── golf_simulator/
│   │   │   └── contacted_users.txt
│   │   └── stock/
│   │       └── contacted_users.txt
│   ├── TikTok/                    # TikTok 已触达用户记录
│   │   ├── golf/
│   │   ├── stock/
│   │   └── contacted_users.txt
│   ├── TraderView/                # TradingView 已触达用户记录及配置
│   │   ├── contacted_users.txt
│   │   ├── first_message.txt
│   │   ├── keywords.txt
│   │   ├── prompts.txt
│   │   └── 关键词+私信文案.docx
│   ├── Twitter/                   # Twitter 已触达用户记录
│   │   ├── golf/
│   │   └── stock/
│   ├── v2rayN/                    # 代理配置
│   │   └── myClashConfig.yaml
│   └── 私信提示词_golf.txt         # 高尔夫业务私信提示词
├── scraper-demo/                  # 独立爬虫演示项目（TypeScript）
│   ├── src/
│   │   └── index.ts               # Express + Playwright 服务入口
│   ├── package.json               # Node.js 依赖配置
│   ├── scrape.py                  # Python 爬虫脚本
│   ├── cookies.txt                # Cookie 文件
│   └── README.md
├── src/                           # 核心源代码目录
│   ├── Facebook/                  # Facebook 平台模块
│   ├── Instagram/                 # Instagram 平台模块
│   ├── Pinterest/                 # Pinterest 平台模块
│   ├── Reddit/                    # Reddit 平台模块（完整获客流程）
│   ├── TikTok/                    # TikTok 平台模块（多业务线）
│   ├── TraderView/                # TradingView 平台模块（完整获客流程）
│   ├── Twitter/                   # Twitter/X 平台模块（完整获客流程）
│   ├── Xiaohongshu/               # 小红书平台模块
│   ├── Youtube/                   # YouTube 平台模块
│   └── utils/                     # 公共工具库
├── note.md                        # 开发笔记与 TODO 清单
└── run.log                        # 运行日志
```

---

## 三、核心模块详解

### 3.1 conf/ — 配置文件

| 文件 | 说明 |
|------|------|
| `api_key.json` | 存储 DeepSeek 大模型 API Key，供 AI 意图判定使用 |

### 3.2 src/utils/ — 公共工具库

| 文件 | 说明 |
|------|------|
| `common_utils.py` | 核心工具函数集合，被所有平台模块引用 |

**`common_utils.py` 主要函数说明：**

| 函数名 | 功能描述 |
|--------|----------|
| `load_contacted_users()` | 加载已触达用户列表（去重用） |
| `parse_cookie_string()` | 解析浏览器 Cookie（支持 JSON 和键值对格式） |
| `parse_product_dimensions()` | 解析亚马逊商品尺寸字符串 |
| `get_text_response_ds()` | 调用 DeepSeek API 获取 AI 文本响应（意图判定核心） |
| `insert_validation_column()` | 向 Excel 插入下拉验证列 |
| `generate_upc_list()` | 批量生成 UPC-A 条码 |
| `generate_ean13_list()` | 批量生成 EAN-13 条码 |
| `human_scroll()` | 模拟人类滚动行为（反爬虫） |
| `generate_hash_digits()` | 生成字符串哈希值 |
| `generate_utc_time_strings()` | 生成 UTC 时间字符串 |
| `get_adspower_ws()` | 获取 AdsPower 指纹浏览器的 CDP 调试地址 |

### 3.3 src/Reddit/ — Reddit 模块

完整的获客流程模块，支持高尔夫和股票两条业务线。

| 文件 | 说明 |
|------|------|
| `run.py` | 主入口（高尔夫业务），串联搜索→爬评论→AI筛选→发私信全流程 |
| `run_stock.py` | 股票业务主入口 |
| `scrape_articles_v0.py` | 爬取 Subreddit 帖子列表（滚动加载、解析帖子元数据） |
| `scrape_reviews_v0.py` | 爬取帖子评论区（自动展开"查看更多回复"、深度加载） |
| `chat_v0.py` | 发送 Reddit 私信（含拟人化浏览行为模拟） |
| `chat_v0_stock.py` | 股票业务私信发送 |

**业务流程：**
1. `scrape_articles_v0` → 按关键词搜索 Subreddit，滚动加载帖子列表
2. `scrape_reviews_v0` → 进入帖子详情页，递归加载并解析所有评论
3. `is_target_user()` → 调用 DeepSeek API 判断评论者是否为潜在客户
4. `chat_v0` → 向目标用户发送私信，记录已触达用户

### 3.4 src/TikTok/ — TikTok 模块

按业务线和功能拆分为多个子目录。

```
TikTok/
├── common/                        # 公共爬虫组件
│   ├── scrape_reviews_v0.py       # 评论爬取（含限流检测与拟人刷新）
│   └── search_keywords_v0.py      # 关键词搜索视频列表
├── golf/                          # 高尔夫业务
│   ├── 0_scrape_videos.py         # 步骤0：爬取视频列表
│   ├── 1_reply_comments.py        # 步骤1：回复评论
│   ├── 1_send_messages.py         # 步骤1：发送私信
│   ├── chat_v0.py                 # 私信发送核心逻辑（含关注+私信）
│   └── run_auto_reply.py          # 自动回复运行入口
└── stock/                         # 股票业务
    ├── 0_scrape_vidoes.py         # 步骤0：爬取视频列表
    └── 1_send_messages.py         # 步骤1：发送私信
```

**关键技术点：**
- 使用 `launch_persistent_context` 保持登录态
- 添加 `--disable-blink-features=AutomationControlled` 绕过反爬检测
- 私信发送前模拟真人点击（hover → mouse.down → mouse.up）
- 评论区限流检测（"Start the conversation" 空状态占位符）
- 定期回首页刷会话状态（`_mimic_tiktok_feed`）

### 3.5 src/Twitter/ — Twitter/X 模块

完整的获客流程模块。

| 文件 | 说明 |
|------|------|
| `run.py` | 主入口（高尔夫业务），全流程串联 |
| `run_stock.py` | 股票业务主入口 |
| `run.sh` | Shell 启动脚本 |
| `search_keywords_v0.py` | 关键词搜索推文（支持按时间过滤、滚动加载、去重） |
| `scrape_reviews_v0.py` | 爬取推文评论（解析评论层级关系、构建回复线程） |
| `scrape_profile.py` | 爬取用户 Profile 信息 |
| `chat_v0.py` | 发送私信（当前被注释，未启用） |
| `chat_v0_stock.py` | 股票业务私信发送 |
| `Trash/` | 废弃代码 |

**关键技术点：**
- 搜索支持 `--search-by-latest` 按最新排序
- 评论解析支持层级关系（`build_reply_threads`、`build_indent_levels`）
- 通过 AdsPower 指纹浏览器实现多账号切换

### 3.6 src/TraderView/ — TradingView 模块

完整的获客流程模块。

| 文件 | 说明 |
|------|------|
| `run.py` | 主入口，串联搜索→爬评论→筛选→发私信全流程 |
| `search_keywords_v0.py` | 搜索 TradingView 文章（滚动加载 Spinner） |
| `scrape_reviews_v0.py` | 爬取文章评论区（递归展开"more replies"） |
| `chat_v0.py` | 发送私信（检测错误弹窗、处理私信限制） |
| `check_new_message.py` | 检查是否有新的私信回复 |
| `login.py` | 登录辅助脚本 |

### 3.7 src/Facebook/ — Facebook 模块

| 文件 | 说明 |
|------|------|
| `scrape_reviews_v0.py` | Facebook 评论爬取（支持多语言"加载更多"按钮） |
| `auth.json` | Facebook 认证信息 |

### 3.8 src/Instagram/ — Instagram 模块

| 文件 | 说明 |
|------|------|
| `scrape_reviews_v0.py` | Instagram 帖子评论爬取（激活评论区面板、滚动加载） |

### 3.9 src/Pinterest/ — Pinterest 模块

| 文件 | 说明 |
|------|------|
| `scrape_reviews_v0.py` | Pinterest 评论爬取（展开评论区、滚动加载） |

### 3.10 src/Youtube/ — YouTube 模块

| 文件 | 说明 |
|------|------|
| `scrape_reviews_v0.py` | YouTube Shorts 评论爬取（点击评论按钮、滚动加载） |

### 3.11 src/Xiaohongshu/ — 小红书模块

| 文件 | 说明 |
|------|------|
| `scrape_reviews_v0.py` | 小红书评论爬取（检测"THE END"判断到底） |
| `auth.json` | 小红书认证信息 |

### 3.12 scraper-demo/ — 独立爬虫演示

独立的 TypeScript + Python 混合项目，提供 Express HTTP 服务。

| 文件 | 说明 |
|------|------|
| `src/index.ts` | Express 服务入口，集成 Playwright |
| `scrape.py` | Python 爬虫脚本 |
| `package.json` | Node.js 依赖（express、playwright、cors） |
| `cookies.txt` | 浏览器 Cookie 文件 |

---

## 四、数据文件说明（files/）

| 路径 | 说明 |
|------|------|
| `files/{Platform}/{业务线}/contacted_users.txt` | 各平台各业务线已触达用户记录（每行一个用户名） |
| `files/TraderView/keywords.txt` | TradingView 搜索关键词列表 |
| `files/TraderView/prompts.txt` | TradingView AI 意图判定提示词 |
| `files/TraderView/first_message.txt` | TradingView 首条私信模板 |
| `files/v2rayN/myClashConfig.yaml` | Clash 代理配置文件 |
| `files/私信提示词_golf.txt` | 高尔夫业务通用私信提示词 |

---

## 五、关键技术栈

| 技术 | 用途 |
|------|------|
| Python 3.8+ | 主要开发语言 |
| Playwright (async) | 浏览器自动化（爬虫 + 私信发送） |
| DeepSeek API | AI 大模型意图判定（判断用户是否为潜在客户） |
| AdsPower | 指纹浏览器（多账号管理、反检测） |
| OpenAI SDK | 统一的大模型调用接口 |
| openpyxl | Excel 数据处理 |
| pandas | 数据清洗与分析 |
| TypeScript + Express | scraper-demo 的 HTTP 服务 |

---

## 六、核心业务流程

```
┌──────────────────────────────────────────────────────────────────┐
│                        自动化获客流程                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 关键词搜索                                                    │
│     └── 在各平台按关键词搜索帖子/视频/文章                          │
│                                                                  │
│  2. 内容爬取                                                      │
│     └── 滚动加载 → 解析帖子列表 → 进入详情页爬取评论                │
│                                                                  │
│  3. AI 意图判定                                                   │
│     └── 将帖子内容 + 评论内容喂给 DeepSeek                         │
│     └── AI 返回 yes/no 判断是否为潜在客户                          │
│                                                                  │
│  4. 去重过滤                                                      │
│     └── 对比 contacted_users.txt 剔除已触达用户                    │
│     └── 剔除帖子作者                                               │
│                                                                  │
│  5. 自动私信触达                                                  │
│     └── 拟人化行为模拟（随机滚动、随机停顿、模拟点击）               │
│     └── 发送预设话术/个性化私信                                     │
│     └── 记录已触达用户                                             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 七、配置文件说明

### 7.1 Chrome 用户数据目录

各模块通过 `USER_DATA_DIR` 指定 Chrome 持久化数据目录，用于保持登录态：
- 默认路径：`/Users/coast/Desktop/Chrome_Bot_Data`
- Twitter 使用：`/Users/coast/Desktop/Chrome_Bot_Data_1`

### 7.2 AdsPower 指纹浏览器

通过 `get_adspower_ws()` 函数获取 CDP 调试地址，实现多账号切换：
- 默认 API 地址：`http://127.0.0.1:50325`
- 通过 `ADSPOWER_USER_ID` 指定不同账号

### 7.3 AI 意图判定

通过 `get_text_response_ds()` 调用 DeepSeek API：
- API Base URL：`https://api.deepseek.com/v1`
- 默认模型：`deepseek-v4-flash`
- 判定逻辑：输入帖子内容 + 评论内容，输出 `yes`（潜在客户）或 `no`

---

## 八、运行方式

各平台模块通常通过 `run.py` 或 `run_{业务线}.py` 作为入口直接运行：

```bash
# Reddit 高尔夫业务
python src/Reddit/run.py

# Reddit 股票业务
python src/Reddit/run_stock.py

# TikTok 高尔夫业务
python src/TikTok/golf/0_scrape_videos.py
python src/TikTok/golf/1_send_messages.py

# Twitter 高尔夫业务
python src/Twitter/run.py

# TradingView
python src/TraderView/run.py
```

---

## 九、注意事项

1. **登录态维护**：首次运行需手动登录，后续通过 `launch_persistent_context` 自动保持
2. **反爬虫策略**：添加 `--disable-blink-features=AutomationControlled` 参数
3. **私信限制**：TikTok 私信长度限制 350 字符；发送过快会触发限制
4. **账号安全**：爬虫账号和被爬账号分离；使用指纹浏览器降低封号风险
5. **去重机制**：通过 `contacted_users.txt` 文件记录已触达用户，避免重复联系
