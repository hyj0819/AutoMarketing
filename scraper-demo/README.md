# 本地爬虫服务

调用 Python 版本的 TikTok 评论爬虫，Node.js 服务提供 HTTP API。

## 安装步骤

### 1. 安装 Python 依赖

```bash
# 进入目录
cd scraper

# 安装 playwright
pip3 install playwright

# 安装浏览器
python3 -m playwright install chromium
```

### 2. 配置 Cookie

```bash
# 复制示例文件
cp cookies.txt.example cookies.txt

# 编辑 cookies.txt，粘贴你的 TikTok 登录 Cookie
# 获取方法见上面的说明
```

### 3. 设置代理

```bash
# 根据你的科学上网软件调整端口
export HTTP_PROXY="http://127.0.0.1:7890"
export HTTPS_PROXY="http://127.0.0.1:7890"
```

### 4. 启动服务

```bash
# 安装 Node.js 依赖（仅用于 API 服务）
npm install

# 启动
npm start
```

## 测试

```bash
curl -X POST http://localhost:3001/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://www.tiktok.com/@binruimattress/video/7607251478830451999"],"filter":{}}'
```

## 健康检查

```bash
curl http://localhost:3001/health
```
