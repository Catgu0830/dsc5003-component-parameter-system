后端交付-已修改
================
目录：
  backend/    Flask + SQLite（11 表、参数级审核）
  最强RAG/    PDF/URL 提取所需的最小 RAG 源码
启动：
  cd backend
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  .\.venv\Scripts\python.exe -m flask --app backend:create_app create-user --username admin --role admin
  .\.venv\Scripts\python.exe run.py
健康检查：http://127.0.0.1:5000/api/health

可选：使用演示数据库
  $env:DATABASE = "D:\...\Database\db\demo.db"
  .\.venv\Scripts\python.exe run.py

RAG：默认读取同级 最强RAG；也可设置 RAG_HOME。
DASHSCOPE_API_KEY 请通过环境变量或 最强RAG/.env 提供，交付包不包含真实密钥。
首次启动会创建 backend/instance/components.sqlite3 和上传目录。
