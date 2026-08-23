# 抖音爬虫适配与 Worker 参数管理开发记录

## 文档信息

| 属性 | 内容 |
|------|------|
| **开发日期** | 2026-08-23 |
| **涉及模块** | 抖音爬虫、Worker 引擎、参数管理 |
| **文档版本** | v1.0 |

---

## 一、AdsPower 指纹浏览器架构梳理

### 1.1 两种浏览器模式

项目中存在两种浏览器启动方式，由任务创建时是否选择「执行账号」决定：

| 模式 | 触发条件 | 浏览器来源 | 适用场景 |
|------|----------|------------|----------|
| **AdsPower 指纹浏览器模式** | 任务选择了执行账号（`account_id` 不为空） | AdsPower 本地 API 启动档案，返回 WebSocket CDP 地址，Playwright 通过 `connect_over_cdp()` 连接 | TikTok 出海、需要多账号隔离的场景 |
| **本地 Chrome Profile 模式** | 未选择执行账号 | Playwright `launch_persistent_context()` 直接打开本地 Chrome profile 目录 | 抖音国内、不需要指纹隔离的场景 |

### 1.2 AdsPower 连接流程

```
前端选择账号 → task_executions.account_id 写入
                      ↓
Worker 读取 account_config → 获取 browser_id（即 AdsPower user_id）
                      ↓
调用 AdsPower API: GET /api/v1/browser/start?user_id=xxx
                      ↓
返回 websocket 调试地址
                      ↓
Playwright connect_over_cdp(ws_endpoint) → 控制浏览器
```

**关键代码**：`src/utils/common_utils.py` 中的 `get_adspower_ws()` 函数。

### 1.3 自动降级机制

当 AdsPower 连接失败时（服务未启动、档案不存在等），Pipeline 会自动降级为本地 Chrome Profile 模式：

```python
if not ws_endpoint:
    ctx.log("warning", "AdsPower 连接失败，自动降级为本地浏览器模式")
    context = await p.chromium.launch_persistent_context(profile_dir, ...)
```

### 1.4 抖音不需要指纹浏览器

**结论**：国内抖音完全不需要 AdsPower 指纹浏览器，原因如下：

- 国内直连 IP 天然正常访问，不存在地域限制
- 使用指纹浏览器反而需要配置代理，增加被识别为机房 IP / 海外 IP 的风险
- AdsPower 中打开抖音曾出现「访问受限，实名认证」提示，即代理 IP 被识别

**推荐方案**：抖音任务不选择执行账号，直接使用本地 Chrome Profile 模式（`chrome_data/Chrome_Bot_Data_DY`）。

---

## 二、Worker 任务引擎问题排查

### 2.1 孤儿任务问题

**现象**：任务创建并启动后，Worker 日志无任何输出，任务状态一直是 `running` 但没有进展。

**原因**：Worker 进程在认领任务后崩溃（或被 kill），但任务状态已更新为 `running`。新启动的 Worker 只认领 `status='queued'` 的任务，不会重新捡起 `running` 状态的孤儿任务。

**任务状态机**：

```
pending → queued → running → success / failed / cancelled
                 ↑
          Worker 认领时更新
```

**解决方案**：手动将孤儿任务状态重置为 `queued`（或 `pending` 让前端重新启动）：

```sql
UPDATE task_executions SET status = 'pending',
    start_time = NULL, end_time = NULL, error_message = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 56;
```

**经验教训**：未来应考虑在 Worker 启动时扫描 `running` 状态的任务，如果对应的 Worker 进程已不存在，则自动重置为 `queued`。

### 2.2 Chrome Profile 占用问题

**现象**：启动诊断脚本时报错 `Chrome profile 被占用`。

**原因**：前一个 Worker 进程异常退出，Chrome 子进程未被正确清理，profile 目录的 lock 文件未释放。

**解决方案**：

```bash
# 查找残留进程
ps aux | grep "Chrome_Bot_Data_DY" | grep -v grep
# 强制清理
kill <PID>
```

---

## 三、抖音搜索爬虫兼容性修复

### 3.1 问题背景

抖音频繁更新 DOM 结构，原有选择器 `div[class*="DivItemContainer"]` 匹配不到任何元素，导致搜索阶段一直输出「轮次 N: 未检测到元素」。

### 3.2 修复方案

**文件**：`src/Douyin/common/search_keywords_douyin.py`

#### 3.2.1 多版本选择器 + 动态检测

定义 5 个备选选择器，运行时逐个检测，使用第一个能匹配到元素的选择器：

```python
ITEM_SELECTORS = (
    'div[class*="DivItemContainer"]',           # 旧版
    'div[class*="DivVideoCard"]',                # 中间版本
    'div[class*="VideoCard"]',                   # 另一种变体
    'div[class*="search-result"] a[href*="/video/"]',  # 搜索结果链接
    'a[href*="/video/"]',                        # 最终兜底
)
```

#### 3.2.2 回退直采模式

当所有容器选择器都匹配不到时，直接通过 `a[href*="/video/"]` 链接采集视频数据：

```python
if not active_selector:
    active_selector = 'a[href*="/video/"]'  # 回退到视频链接直采
```

回退模式下，容器本身就是 `<a>` 标签，直接从 `href` 属性提取视频链接。

#### 3.2.3 诊断函数

新增 `_diagnose_page()` 函数，在搜索开始前输出页面诊断信息：

- 当前页面 URL 和标题（确认是否跳转到登录页）
- 检测登录/验证弹窗（自动按 Escape 关闭）
- 统计 `a[href*="/video/"]` 链接数（最可靠的信号）
- 逐个报告各选择器的匹配情况
- 无匹配时输出页面 HTML 前 2000 字符（用于分析 DOM 结构变化）

#### 3.2.4 使用系统 Chrome 而非 Playwright 内置 Chromium

**关键修改**：所有 `launch_persistent_context` 调用必须添加 `channel="chrome"` 参数。

```python
context = await p.chromium.launch_persistent_context(
    profile_dir,
    channel="chrome",   # 使用系统安装的 Chrome
    headless=headless,
    ...
)
```

**原因**：抖音的反爬机制能检测 Playwright 内置 Chromium 的自动化特征（如 `navigator.webdriver` 属性），使用系统 Chrome 可大幅降低被检测概率。

### 3.3 URL 重复拼接 Bug

**现象**：评论爬取阶段 URL 格式异常：

```
错误: https://www.douyin.com//www.douyin.com/video/7580683486692986175
正确: https://www.douyin.com/video/7580683486692986175
```

**原因**：抖音 `<a>` 标签的 `href` 属性值是协议相对路径格式 `//www.douyin.com/video/xxx`，原代码判断 `startswith('/')` 为 true，又拼接了一次域名前缀。

**修复**：新增 `_normalize_douyin_url()` 函数统一处理三种 href 格式：

| href 格式 | 处理方式 | 结果 |
|---|---|---|
| `https://www.douyin.com/video/xxx` | 直接返回 | 原值 |
| `//www.douyin.com/video/xxx` | 加 `https:` 前缀 | `https://www.douyin.com/video/xxx` |
| `/video/xxx` | 加 `https://www.douyin.com` 前缀 | `https://www.douyin.com/video/xxx` |

---

## 四、抖音评论爬取修复

### 4.1 问题诊断

通过编写诊断脚本 `tmp/diagnose_douyin_comments.py` 打开真实视频页面，发现：

- **评论已直接加载在页面右侧面板**，`data-e2e="comment-item"` 有 5 个可见元素
- **不需要点击任何评论按钮**，评论是自动展示的
- 原有的 4 个评论按钮选择器**全部返回 0 个匹配**
- 实际的评论图标选择器是 `data-e2e="feed-comment-icon"`（不是 `data-e2e="comment-icon"`）

### 4.2 修复方案

**文件**：`src/Douyin/common/scrape_reviews_douyin.py`

#### 4.2.1 评论检测逻辑调整

原逻辑：必须先找到并点击「评论按钮」→ 等待评论加载 → 采集。找不到按钮就返回失败。

新逻辑：
1. 先检查评论是否已直接加载（`div[data-e2e="comment-item"]`）
2. 有评论元素 → 直接采集，无需点击任何按钮
3. 没有评论元素 → 才尝试点击评论按钮展开
4. 按钮也找不到 → 返回失败

```python
existing_items = page.locator('div[data-e2e="comment-item"]')
existing_count = await existing_items.count()

if existing_count > 0:
    log("info", f"评论区已直接加载，检测到 {existing_count} 条评论")
else:
    # 评论未直接显示，尝试点击评论按钮展开
    if not await _click_comment_button(page, timeout_ms):
        return comments, "unavailable"
```

#### 4.2.2 评论按钮选择器更新

新增诊断发现的实际选择器 `feed-comment-icon`：

```python
COMMENT_BUTTON_SELECTORS = (
    '[data-e2e="feed-comment-icon"]',          # 新增：实际侧边栏评论图标
    'button[data-e2e="comment"]',
    'div[role="button"][data-e2e="comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[role="button"][aria-label*="评论"]',
)
```

#### 4.2.3 评论文本提取增强

新增回退逻辑：当专用选择器无法提取评论文本时，从整个评论项提取 `inner_text()`，并自动过滤 UI 噪音：

- 过滤按钮文本：「分享」「回复」「展开」「...」「收起」
- 过滤时间戳：「X月前」「X天前」「小时前」「刚刚」
- 过滤纯数字（点赞数）

---

## 五、Worker 参数管理集成

### 5.1 需求背景

原先 Worker 的无头模式（`headless`）和轮询间隔（`poll_interval`）通过 `.env` 环境变量配置。项目已有完善的参数管理功能（前端页面 + 后端 API + 数据库），希望将这些配置统一到参数管理中。

### 5.2 现有参数管理架构

| 层级 | 文件 | 功能 |
|------|------|------|
| **前端** | `src/views/system/configs/index.vue` | 分组 Tab + 行内编辑 + 脏数据追踪 + 批量保存 |
| **前端 API** | `src/api/system/configs.ts` | CRUD 接口调用 |
| **后端 API** | `src/api/routes/system_configs.py` | 列表/分组/更新/批量更新 |
| **数据库** | `system_configs` 表 | `config_group` + `config_key` 唯一约束 |

已有的参数分组：

| 分组 | 标签 | 参数示例 |
|------|------|----------|
| `risk_control` | 风控策略 | 私信发送间隔、每日上限 |
| `ai` | AI 配置 | DeepSeek 模型名称、私信最大字数 |

### 5.3 新增 Worker 分组参数

在 `system_configs` 表中新增 `worker` 分组：

| config_key | value_type | 默认值 | 标签 | 说明 |
|---|---|---|---|---|
| `headless` | boolean | `false` | 无头模式 | 浏览器是否在后台运行 |
| `poll_interval` | number | `3` | 轮询间隔(秒) | Worker 检查新任务的间隔时间 |
| `comment_scroll_pause` | number | `2` | 评论滚动间隔(秒) | 爬取评论时滚动暂停的等待时间 |

### 5.4 前端支持 boolean 类型

**文件**：`naive-ui-admin/src/views/system/configs/index.vue`

原参数管理只支持 `number`（数字输入框）和 `string`（文本输入框）两种类型。新增 `boolean` 类型支持，渲染为 `NSwitch` 开关组件：

```typescript
if (row.value_type === 'boolean') {
    const boolVal = row.config_value === 'true';
    return h(NSwitch, {
        value: boolVal,
        size: 'small',
        onUpdateValue: (val: boolean) => {
            row.config_value = String(val);
            // 脏数据追踪逻辑...
        },
    });
}
```

### 5.5 后端分组标签

**文件**：`src/api/routes/system_configs.py`

`_group_label()` 函数新增 `worker` 分组的中文标签：

```python
labels = {
    "risk_control": "风控策略",
    "ai": "AI 配置",
    "system": "系统参数",
    "worker": "Worker 配置",   # 新增
}
```

### 5.6 Worker 读取优先级改造

**文件**：`src/worker/config.py`

`is_headless()` 和 `get_poll_interval()` 改为优先从数据库读取，读不到才回退到环境变量：

```
优先级：system_configs 表（worker 分组）→ .env 环境变量 → 代码默认值
```

新增通用函数 `_get_worker_config(key)`：

```python
def _get_worker_config(key: str, default=None):
    """从 system_configs 读取 worker 分组参数"""
    row = db.execute(
        text("SELECT config_value FROM system_configs "
             "WHERE config_group='worker' AND config_key=:key"),
        {"key": key},
    ).fetchone()
    return row[0] if row else default
```

**优势**：
- 在前端「参数管理」页面即可修改 Worker 行为，无需重启服务
- 修改后下一次任务执行立即生效（Worker 每次执行时实时读取）
- 保留了 `.env` 兜底能力，数据库异常时不会崩溃

### 5.7 种子数据同步

**文件**：`scripts/init_db.py`

在 `init_base_data()` 中新增 Worker 分组的种子数据，确保未来重新初始化数据库时不会丢失：

```python
('worker', 'headless', 'false', 'boolean', '无头模式', '浏览器是否在后台运行，开启后不弹出 Chrome 窗口', 1),
('worker', 'poll_interval', '3', 'number', '轮询间隔(秒)', 'Worker 检查新任务的间隔时间', 2),
('worker', 'comment_scroll_pause', '2', 'number', '评论滚动间隔(秒)', '爬取评论时滚动暂停的等待时间', 3),
```

---

## 六、修改文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/Douyin/common/search_keywords_douyin.py` | 重写 | 多版本选择器、诊断函数、回退直采、URL 规范化、`channel="chrome"` |
| `src/Douyin/common/scrape_reviews_douyin.py` | 重写 | 评论直接加载检测、按钮选择器更新、文本提取回退增强 |
| `src/worker/pipelines/douyin_scrape.py` | 修改 | 3 处 `launch_persistent_context` 添加 `channel="chrome"` |
| `src/worker/config.py` | 修改 | `is_headless()` 和 `get_poll_interval()` 改为 DB 优先；新增 `_get_worker_config()` |
| `src/api/routes/system_configs.py` | 修改 | `_group_label()` 新增 `"worker": "Worker 配置"` |
| `scripts/init_db.py` | 修改 | 种子数据新增 worker 分组 3 条记录 |
| `naive-ui-admin/src/views/system/configs/index.vue` | 修改 | 新增 `boolean` 类型的 `NSwitch` 渲染支持 |
| `automarketing.db` | 数据变更 | `system_configs` 表插入 3 条 worker 分组记录 |

---

## 七、注意事项与经验总结

### 7.1 抖音反爬要点

| 要点 | 说明 |
|------|------|
| **必须使用 `channel="chrome"`** | Playwright 内置 Chromium 会被抖音检测，必须使用系统 Chrome |
| **不要用代理** | 国内抖音直连即可，代理反而容易触发「访问受限」 |
| **DOM 结构频繁变化** | 选择器需要多版本兜底 + 动态检测 + 回退策略 |
| **评论自动加载** | 抖音视频页评论直接在右侧面板渲染，不需要点击按钮 |
| **href 格式多样** | 协议相对路径 `//`、绝对路径 `/`、完整 URL 三种都可能出现 |

### 7.2 Worker 任务引擎要点

| 要点 | 说明 |
|------|------|
| **孤儿任务需处理** | Worker 崩溃后任务停留在 `running`，新 Worker 不会捡起 |
| **Chrome profile 互斥** | 同一 profile 目录同时只能被一个进程使用，异常退出需手动清理 |
| **配置优先级** | DB > .env > 代码默认值，保证灵活性和兜底能力 |

### 7.3 参数管理扩展建议

当前参数管理已支持三种值类型：

| value_type | 前端控件 | 适用场景 |
|---|---|---|
| `string` | NInput 文本输入框 | 模型名称、URL 等 |
| `number` | NInputNumber 数字输入框 | 间隔时间、数量上限等 |
| `boolean` | NSwitch 开关 | 功能开关（无头模式、AI 筛选等） |

未来新增 Worker 参数（如超时时间、最大重试次数等）只需在 `system_configs` 表插入记录，前端自动展示，无需改代码。

---

**文档版本**：v1.0
**生成日期**：2026-08-23
**维护者**：AutoMarketing Team
