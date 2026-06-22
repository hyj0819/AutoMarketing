import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from time import sleep
USER_DATA_DIR = "/Users/coast/Desktop/Chrome_Bot_Data" 


async def check_tradingview_messages(page):
    # 1. 检查侧边栏是否有未读消息红点
    # 根据 a.txt，未读数位于 span.counter-napy2vLF
    chat_button_selector = 'button[data-name="union_chats"]'
    counter_selector = f'{chat_button_selector} .counter-napy2vLF'
    sleep(8)
    unread_count_element = await page.query_selector(counter_selector)
    
    if not unread_count_element:
        print("没有发现未读消息。")
        return

    unread_total = await unread_count_element.inner_text()
    print(f"发现 {unread_total} 条未读消息，正在展开列表...")

    # 2. 点击展开聊天列表
    await page.click(chat_button_selector)
    # 等待列表加载（根据 b.txt 的容器类名）
    await page.wait_for_selector('.msg-data')

    # 3. 提取所有有未读消息的用户详情
    # 获取当前列表页面的 HTML 内容进行解析
    list_html = await page.content()
    soup = BeautifulSoup(list_html, 'html.parser')
    
    # 查找所有消息条目
    items = soup.find_all('div', class_='msg-item')
    new_messages = []

    for item in items:
        # 检查该条目的未读计数
        counter_div = item.find('div', class_='counter')
        if counter_div and counter_div.text.strip() != '0':
            user_name = item.find('div', class_='title').find('div').text.strip()
            last_msg = item.find('span', class_='last-message').text.strip()
            unread_num = counter_div.text.strip()
            
            new_messages.append({
                "user": user_name,
                "count": unread_num,
                "content": last_msg
            })

    # 打印提取结果
    if new_messages:
        print("\n--- 新消息详情 ---")
        for msg in new_messages:
            print(f"用户: {msg['user']} ({msg['count']}条新消息)")
            print(f"最新预览: {msg['content']}\n")
    else:
        print("列表已展开，但未找到具体的未读条目。")

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            no_viewport=False
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 假设您已经跳转到了 TradingView 相关页面
        await page.goto("https://www.tradingview.com/")
        #sleep(300000)

        await check_tradingview_messages(page)
        #await context.close()

if __name__ == "__main__":
    asyncio.run(main())