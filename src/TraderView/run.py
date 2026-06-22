from search_keywords_v0 import search_tradingview
from scrape_reviews_v0 import scrape_tradingview_comments
from chat_v0 import send_tradingview_message
import sys
import os
sys.path.append('src/utils')
from common_utils import get_text_response_ds
from random import randint, choice
import asyncio

search_words = ['Buy stocks'] #, 'Buy stocks', 'Stock picks', 'Stocks today', 'Stock movement', 'Hot stocks', 'Stock trade', 'Stock investing', 'Stock portfolio', 'Stock watchlist','AI stocks', 'Semiconductor stocks', 'Consumer stocks', 'What to buy', 'Technical analysis', 'Stock ideas', 'Stock opinions', 'How to buy stocks', 'Stock for beginners', 'Make money with stocks', 'Stock tips', 'Trading strategy', 'Avoid these mistakes']
contacted_user_files = 'files/TraderView/contacted_users.txt'
messages = [
    ("I see you’re looking for stock ideas and setups in the comments. You want something actionable, right?", "My creator can’t share these publicly. I’ll send you some directly. Just add me on WhatsApp."),
    ("What you’ve been looking for, I can actually get for you.", "Add me on WhatsApp if you want, I’ll send them straight to you."),
    ("Must be tiring waiting in comments all the time. Let me help you out.", "Add me on WhatsApp and I’ll send you some stocks to watch right now."),
    ("I have some stock ideas from our creator that I can send you.", "Add me on WhatsApp, I’ll send them to you directly."),
    ("I can send you some stock ideas.", "Just add me on WhatsApp.")
    ]


contacted_users = []
if os.path.exists(contacted_user_files):
    for line in open(contacted_user_files).readlines():
        if line != '' and line != '\n':
            contacted_users.append(line.strip().split("\t"))


searched_articles = set([])
for search_word in search_words:
    searched_articles.update(asyncio.run(search_tradingview(search_word)))

searched_articles = list(searched_articles)[:20]
print(f'searched_articles cnt:{len(searched_articles)}')

target_customers = set([])
for article_idx, article in enumerate(searched_articles):
    print(f'processing article: {article_idx+1}/{len(searched_articles)}...')
    article_link = article[1]
    print(f'\tscraping comments from article:{article[0]}, {article_link}')

    article_info = asyncio.run(scrape_tradingview_comments(article_link))
    if 'comments' not in article_info:
        continue 

    comments = article_info['comments']
    author = article_info['post_author']

    author_name = author['username']
    author_url = author['profile_url']

    for comment in comments:
        # 剔除掉文章作者
        if comment['username'] != author_name and comment['profile_url'] != author_url:
            is_target_user = True #get_text_response_ds(f"You are a helpful assistant that can analyze reviews and provide insights. You are given a review and you need to analyze it decide if the reviewer is a potential customer. The review is: {comment['content']}", "Please analyze the comment and determine whether the reviewer is a potential customer or has purchase intent, with slightly relaxed judgment criteria. Return only the answer(yes or no), no other text.")

            # 剔除掉已经发过私信的用户
            if is_target_user and comment['username'] not in [x[0] for x in contacted_users] and comment['profile_url'] not in [x[1] for x in contacted_users]:
                target_customers.add((article_link, comment['username'], comment['profile_url']))
                #target_customers.append(("", "coastchb", "https://www.tradingview.com/u/coastchb/"))
            else:
                print(f'\t{comment["username"]}({comment["profile_url"]}) has been contacted, filtered!')
        else:
            print(f'\t{comment["username"]}({comment["profile_url"]}) is the author, filtered!')

target_customers = list(target_customers)[:30]
print(f'target_customers cnt:{len(target_customers)},\ntarget_customers:{target_customers}')

sent_users = []
prev_msg = ''
for target_user_idx, target_user in enumerate(target_customers):
    target_user_name = target_user[1]
    target_user_url = target_user[2]
    message = choice(messages)[0]
    while message == prev_msg:
        message = choice(messages)[0]
    print(f'({target_user_idx+1}/{len(target_customers)}) 准备给潜在客户{target_user_name}({target_user_url})发私信:{message}')
    chat_ret = asyncio.run(send_tradingview_message(target_user_url, message))
    if chat_ret == -1:
        print('私信次数已达上限，终止！')
        break
    elif chat_ret == 0:
        sent_users.append((target_user_name, target_user_url))

    prev_msg = message

if len(contacted_user_files) > 0:
    with open(contacted_user_files, 'a') as fd:
        fd.writelines('\n'.join([f'{x[0]}\t{x[1]}' for x in sent_users]))
        fd.writelines('\n\n')
