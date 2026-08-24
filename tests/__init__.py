r"""RedDream API 测试套件

运行方式：
  # 跑全部单元测试（不需要服务启动）
  .venv\Scripts\python.exe -m pytest tests/ -v -m unit

  # 跑集成测试（需要 Ollama + PostgreSQL 运行中）
  .venv\Scripts\python.exe -m pytest tests/ -v -m integration

  # 跑全部
  .venv\Scripts\python.exe -m pytest tests/ -v

  # 跑单个文件
  .venv\Scripts\python.exe -m pytest tests/test_api_health.py -v
"""
