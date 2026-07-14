# 一、启动脚本

\# 使用已创建的 Python 3.9 虚拟环境

source /Users/hyj/Documents/mywork/AutoMarketing/.venv39/bin/activate

\# 启动后端

cd /Users/hyj/Documents/mywork/AutoMarketing

uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

\# 启动前端

cd /Users/hyj/Documents/mywork/naive-ui-admin

npm run dev

# 二、接口文档

http://localhost:8000/docs