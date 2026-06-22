/**
 * 本地爬虫服务 - 调用 Python 脚本
 */

import express from 'express';
import cors from 'cors';  // 添加这行
import { spawn } from 'child_process';
import { readFileSync, writeFileSync } from 'fs';
import { resolve } from 'path';

const app = express();
app.use(cors());  // 添加这行，允许所有跨域请求
app.use(express.json());

const PORT = 3001;

// 使用 process.cwd() 获取当前目录
const SCRAPER_DIR = process.cwd();
const cookieFilePath = resolve(SCRAPER_DIR, 'cookies.txt');
const scriptPath = resolve(SCRAPER_DIR, 'scrape.py');

// 从文件读取 Cookie
function getCookies(): string | null {
  try {
    const content = readFileSync(cookieFilePath, 'utf-8').trim();
    if (content && content.length > 10) {
      console.log(`[Node] Cookie file loaded (${content.length} chars)`);
      return content;
    }
  } catch {
    console.log(`[Node] Cookie file not found: ${cookieFilePath}`);
  }
  return null;
}

// 调用 Python 爬虫
function scrapeWithPython(videoUrl: string): Promise<any> {
  return new Promise((resolve, reject) => {
    console.log(`[Node] Calling Python with: ${videoUrl}`);
    console.log(`[Node] Script path: ${scriptPath}`);
    
    // 写入 Cookie 到临时文件
    const tempCookieFile = '/tmp/tiktok_cookies.txt';
    writeFileSync(tempCookieFile, getCookies() || '');  // 改用 writeFileSync
    console.log(`[Node] Cookie written to temp file`);
    
    // 传递临时文件路径给 Python
    const args = [scriptPath, videoUrl, tempCookieFile];
    console.log(`[Node] Spawn args:`, args);
    
    const python = spawn('python3', args, {
      cwd: SCRAPER_DIR
    });
    
    console.log(`[Node] Python process spawned, PID: ${python.pid}`);
    
    
    let stdout = '';
    let stderr = '';
    let timeout: NodeJS.Timeout;
    
    // 5分钟超时
    const TIMEOUT_MS = 5 * 60 * 1000;
    timeout = setTimeout(() => {
      console.log(`[Node] Timeout reached, killing process`);
      python.kill();
      reject(new Error('爬虫执行超时（5分钟）'));
    }, TIMEOUT_MS);
    
    python.stdout.on('data', (data) => {
      const text = data.toString();
      console.log(`[Node] stdout received: ${text.substring(0, 100)}...`);
      stdout += text;
    });
    
    python.stderr.on('data', (data) => {
      const text = data.toString();
      console.log(`[Node] stderr received: ${text.substring(0, 100)}...`);
      stderr += text;
      // 打印 Python 的进度信息
      process.stderr.write(data);
    });
    
    python.on('error', (err) => {
      console.log(`[Node] Process error: ${err.message}`);
      clearTimeout(timeout);
      reject(err);
    });
    
    python.on('close', (code) => {
      console.log(`[Node] Process closed with code: ${code}`);
      clearTimeout(timeout);
      if (code !== 0) {
        console.error(`[Node] Python exited with code ${code}`);
        reject(new Error(stderr || `Python exited with code ${code}`));
        return;
      }
      
      try {
        // 尝试从输出中提取 JSON
        const output = stdout.trim();
        console.log(`[Node] Final stdout length: ${output.length}`);
        // 查找最后一个有效的 JSON 对象
        const jsonMatch = output.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          const result = JSON.parse(jsonMatch[0]);
          resolve(result);
        } else {
          console.error(`[Node] No valid JSON found in output:`, output.substring(0, 200));
          reject(new Error('无法解析爬虫输出'));
        }
      } catch (e) {
        console.error(`[Node] Failed to parse Python output:`, stdout.substring(0, 200));
        reject(new Error('Failed to parse Python output'));
      }
    });
    
    python.on('error', (err) => {
      clearTimeout(timeout);
      console.error(`[Node] Python error:`, err.message);
      reject(err);
    });
  });
}

// ... 其余代码不变 ...

// API 类型
interface ScrapeRequest {
  urls: string[];
  filter?: {
    keyword?: string;
    days?: number;
  };
}

// API 路由
app.post('/api/scrape', async (req, res) => {
  try {
    const { urls, filter } = req.body as ScrapeRequest;
    
    if (!urls || !Array.isArray(urls) || urls.length === 0) {
      return res.status(400).json({ success: false, message: '请提供有效的 URL' });
    }
    
    console.log(`\n========== [Node] Request ==========`);
    console.log(`URLs: ${urls.join(', ')}`);
    
    const allReviewers: any[] = [];
    
    for (const url of urls) {
      if (!url) continue;
      
      try {
        const result = await scrapeWithPython(url);
        
        if (result.success && result.data?.reviewers) {
          // 应用筛选
          let reviewers = result.data.reviewers;
          
          if (filter?.keyword) {
            const kw = filter.keyword.toLowerCase();
            reviewers = reviewers.filter((r: any) => 
              (r.content?.toLowerCase() || '').includes(kw) ||
              (r.reviewer?.toLowerCase() || '').includes(kw)
            );
          }
          
          allReviewers.push(...reviewers);
        }
        
      } catch (e) {
        console.error(`[Node] Scrape error for ${url}:`, e);
      }
    }
    
    console.log(`\n🎉 Total: ${allReviewers.length} reviewers`);
    console.log(`==================================\n`);
    
    res.json({
      success: true,
      message: `获取到 ${allReviewers.length} 条评论`,
      data: {
        reviewers: allReviewers,
        totalComments: allReviewers.length
      }
    });
    
  } catch (error) {
    console.error('[Node] Error:', error);
    res.status(500).json({
      success: false,
      message: '服务器错误',
      error: error instanceof Error ? error.message : 'Unknown'
    });
  }
});

app.get('/health', (req, res) => {
  const hasCookies = getCookies() !== null;
  res.json({ 
    status: 'ok', 
    method: 'Python + Playwright',
    cookies: hasCookies ? 'loaded' : 'not found',
    dir: SCRAPER_DIR
  });
});

app.listen(PORT, () => {
  console.log(`
╔═══════════════════════════════════════════════════════╗
║   本地爬虫服务已启动                               ║
║   地址: http://localhost:${PORT}                          ║
║   工作目录: ${SCRAPER_DIR}       ║
║   Cookie: ${getCookies() ? '已加载' : '未找到'}                              ║
╚═══════════════════════════════════════════════════════╝
  `);
});
