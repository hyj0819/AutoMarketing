1、解决使用playwright打开浏览器进行爬虫时，未登录问题：
  参考：https://gemini.google.com/share/3793354339d2
  方法1：使用launch_persistent_context，设置user_data_dir，第一次运行的时候手动登录一下。后续会自动登录；
  方法2：导出并加载 Cookie

2、playwright._impl._errors.TimeoutError: Page.goto: Timeout 30000ms exceeded.
   navigating to "https://www.instagram.com/p/DW9Wp8KDG8A/", waiting until "networkidle"
   解法：将networkidle改为domcontentloaded

3、playwright打开的chrome加载持久化目录，TikTok也还是非登录状态。而且手动登录，不论是使用Google账号登录还是使用手机TK扫码登录都失败
  launch_persistent_context()中加入：args=["--disable-blink-features=AutomationControlled"]，参考TikTok/search_keywords_v0.py

4、如果大模型对html解析失败、错误，可以手动获取html源码，附上源码给大模型，让其分析和理解。

5、TikTok有些用户关闭了私信功能，在发送完私信之后，会显示红色感叹号。网页端似乎没法提前判断是否关闭了。

6、TikTok：对于私密账户或者关闭了私信的用户，可以考虑直接回复他的评论（话术跟私信的要有区别）

7、TikTok，很奇怪的几个点：
（1）爬虫多了，有时候看不了评论区（打开评论区是空的，显示“Start the conversation”），但是能发私信
（2）

8、TikTok私信内容长度有限制，最好控制在350字符以内。

9、TikTok私信违规规则是啥？被封禁的话，是多久？怎么能查询到？

10、
（1）模拟器/股票，都找大v，然后从他们的帖子下面截流
（2）有个经验，在Twitter回复评论的post下的“Discover more”通常会推荐大V的帖子
（3）私信的效果一般（都需要发送私信请求，而且是被折叠状态），可以考虑直接回复评论
（4）在Reddit上通过截流发私信，转化是不错的。但是很可惜，容易被封号

<br>
TODO：<br>
1、Pinterest爬虫，昵称不全的问题。
2、把评论中，作者的所有评论或者回复给剔除掉
3、搜索结果中有些跟关键词无关的内容，该如何识别？
4、有些客户的需求的特定市场（比如非洲），所以需要定位信息
5、不管是搜索、爬评论，都先加载完所有，再统一解析（可以把静态html作为输入，让大模型写解析代码，单独调试）
6、TraderView：注册多个邮箱账号
7、TraderView：完成账号切换
8、TraderView：由于私信的数量限制，最好把获客和建联分开操作。（一个脚本用于搜索帖子和查找客户，然后多账号、多脚本执行建联）
9、TraderView：自动查看是否有私信回复，若有，自动回复。
10、Twitter: 搜索结果中很多是帖子的评论，所以需要根据这个评论找到主帖，然后再爬取所有评论及回复。
11、针对金融业务，stocktwits可以做一下。
12、TK账号，coast0623@gmail.com（谷歌账号登录） 和 coastchb@sina.com（苹果账号登录）都已经无法私信了（但是可以用来爬虫）；coast0623@gmail.com（苹果账号登录）可以私信
13、TK私信的时候，会提示：<div class="css-7btupe-7937d88b--DivNoticeContainer ecftnkw0"><div class="css-1aligtd-7937d88b--DivSendFailTip ecftnkw1">You are sending messages too fast. Take a rest.</div></div>
https://gemini.google.com/app/52c5ae851a31a147  让gemini优化
14、在X上实现多账号发私信（最好用上指纹浏览器）
15、爬取评论的时候，顺便给评论点个赞（点赞那么多，是否会增加反爬虫风控风险？）
16、TikTok: 评论的回复也要处理下（最好把层级关系也保留，把上下文信息都喂给大模型，帮助它准确判断是否有购买意愿）
✅ 17、TikTok: 把发布者的评论给剔除掉（或者把发布者从潜在客户中剔除掉）
18、把TikTok主页显示”private account"的直接过滤掉，不需要发私信了
19、不要直接把私信复制粘贴进输入框，能否调用底层的接口，模拟真人输入？
20、TikTok：在私信的时候会随机刷一些视频，但是互动存在问题。
21、留意一下，在建联的时候，会不会出现已经建联过的用户，还会出现在待建联列表里。（正确的是，在爬取的时候就把这些用户给过滤掉，不要去分析帖子、评论了）
22、优化提示词！（还有很大的提升空间）