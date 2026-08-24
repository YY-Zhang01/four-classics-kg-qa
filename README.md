# 四大名著知识图谱与智能问答系统 · 依赖、目录与运行说明

工程目录：`RedDream/`（本仓库根目录）

一个面向《红楼梦》《三国演义》《水浒传》《西游记》四大名著的多领域知识图谱 + 智能问答系统，覆盖「PDF 解析 → 切块 → 向量化 → KG+向量融合检索 → 大模型受控生成 → Web 流式」全链路。

## 一、目录结构

```text
RedDream/
├── config/                          全局配置（模型/检索/数据库/领域），密钥走 .env
│   ├── settings.py                  集中配置 + 运行时领域/检索状态
│   ├── .env.example                 环境变量模板
│   ├── entities_<领域>.json         人物实体词典（按书分桶）
│   └── domain_<领域>.json           前端 UI 配置（印章字、示例问题）
├── parser/                          PDF 解析（MinerU 封装，run_mineru.py）
├── kb_builder/                      切块（split.py 回目分节 + 滑动窗口，enricher.py 富化）
├── retrieval/                       检索（关键词 / 向量 / KG 融合 / 图谱搜索 / 检索器工厂）
├── kg/                              知识图谱（Schema / 抽取 / 存储 / Neo4j 同步）
├── llm/                             大模型可插拔接入层 + embedding
├── prompts/                         提示词（与代码分离）
├── core/                            受控生成（拼上下文、流式、溯源）+ SSE 编码工具
├── agent/                           Agent 循环与工具（ReAct）
├── router/                          问题智能路由（分类器 / 策略）
├── auth/                            用户认证（JWT + bcrypt）
├── review/                          审核（approve / reject / revise / deprecate）
├── collector/                       数据源扫描与变更检测
├── updater/                         增量更新管线（pipeline / reporter）
├── web/                             FastAPI 服务端 + HTML 前端
│   ├── server.py                    全部 API 路由 + SSE 流式
│   └── static/                      用户端 / 管理后台 / 登录 / 仪表盘页面
├── wiki/                            实体百科页（生成 / 查询 / 存储）
├── scripts/                         工具脚本（建表 / 灌库 / 抓取 / 迁移 / 自检 / 启动 Ollama）
├── tests/                           pytest 测试套件
├── eval/                            评测（Recall@K / MRR / LLM-as-judge）
├── postman/                         Postman 接口测试集合
├── data/                            领域 KG 种子数据
├── logs/                            审计日志（qa_audit.jsonl）
├── main.py                          命令行问答入口
├── requirements.txt                 依赖清单（版本锁定）
└── 问答.bat / 问答.ps1               一键启动命令行问答
```

## 二、项目工作流程

```text
放入名著 PDF 到 pdfs/
    │
    ▼
MinerU 解析（parser/run_mineru.py）
    │  输出 Markdown 到 parsed/
    ▼
切块（kb_builder/split.py）
    │  按回目分节 + 滑动窗口，带 content_hash、页码
    ▼
向量化入库（scripts/ingest_db.py）
    │  bge-m3 生成向量，写入 PostgreSQL chunks 表
    ▼
（可选）知识图谱
    ├── kg/extract.py 抽取人物关系三元组（schema.json 白名单校验）
    ├── 写入 PostgreSQL kg_triples 表
    └── 可选同步 Neo4j（kg/sync_to_neo4j.py）
    ▼
用户提问
    │
    ▼
智能路由（router/）→ 三模检索（retrieval/）
    ├── 关键词：jieba 分词 + 共现
    ├── 语义向量：bge-m3 + 余弦相似度
    └── 融合：KG 结构化事实 + 向量原文块
    ▼
受控生成（core/ask.py）
    │  拼上下文 + 提示词 → Ollama（qwen2.5）流式生成
    ▼
SSE 流式推送（web/server.py）
    │  逐字返回 + 出处 + 图谱 + 原文引用
    ▼
审计日志（logs/qa_audit.jsonl）
```

## 三、依赖与用途

依赖文件：`requirements.txt`

```text
httpx==0.28.1
python-dotenv==1.2.2
jieba==0.42.1
numpy==2.5.1
psycopg2-binary==2.9.12
neo4j==4.4.13
PyJWT==2.13.0
bcrypt==5.0.0
fastapi==0.141.1
uvicorn==0.52.0
pytest==9.1.1
```

| 依赖 | 用途 |
|---|---|
| FastAPI、Uvicorn | Web API 和 ASGI 服务进程 |
| httpx | 调用 OpenAI 兼容接口（本地 Ollama 的 LLM 与 embedding） |
| psycopg2-binary | PostgreSQL 驱动 |
| neo4j | 图谱数据库驱动（可选，未配置时自动降级回 PG） |
| PyJWT、bcrypt | 用户认证：JWT 签发/校验、密码哈希 |
| jieba | 中文分词（关键词检索） |
| numpy | 向量余弦相似度计算 |
| python-dotenv | 从 .env 读取配置 |
| pytest | 测试框架 |

虚拟环境安装位置：`.venv/`（`python -m venv .venv` 后 `pip install -r requirements.txt`）。

MinerU 作为外部 CLI 调用（系统已装），不绑定进本 venv，避免拖重环境。

## 四、外部服务

| 服务 | 用途 |
|---|---|
| PostgreSQL（127.0.0.1:5432，库 reddream） | 知识块、三元组、用户、数据源、审核、审计日志 |
| Ollama（127.0.0.1:11434） | 大模型 qwen2.5:7b 与向量模型 bge-m3 |
| Neo4j（bolt://localhost:7687，可选） | 知识图谱多跳查询（未配置自动回退 PG） |

参数配置在项目根目录 `.env`（模板见 `config/.env.example`，该文件已被 git 忽略）。

## 五、启动、停止和运行

首次初始化：

```powershell
cd E:\ReshapingMyself\projects\RedDream
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\.env.example .env          # 填好本地配置
psql -U postgres -d reddream -f scripts\db_schema.sql   # 一次性建全部表
```

灌数据：

```powershell
python -m parser.run_mineru            # 解析 PDF → parsed/
python -m kb_builder.split             # 切块 → chunks/
python -m scripts.ingest_db            # 向量化入库
python -m scripts.seed_kg              # 灌知识图谱种子
```

启动 Web 服务：

```powershell
python -m web.server
# 用户页面  http://127.0.0.1:7860
# 管理后台  http://127.0.0.1:7860/admin
```

停止：`Ctrl+C`。

命令行问答：双击 `问答.bat`（自动拉起 Ollama 后进入问答），或 `python main.py`。

代码修改后无需重新构建，重启 `python -m web.server` 即可（Python 脚本直接运行，无编译步骤）。

## 六、多领域切换

- 在 `.env` 里设 `PROJECT_NAME` / `PROJECT_DOMAIN` 指定默认书
- 运行时在用户页面下拉框或管理后台切换（红楼梦 / 三国演义 / 水浒传 / 西游记）
- 新增书：把 `entities_<领域>.json`、`domain_<领域>.json` 放入 `config/` 即可动态识别

## 七、测试与评测

`tests/` 分两类：`test_api_*.py`（API 契约，外部依赖 mock）+ `test_unit_real.py`（auth / kg.store / search 的真实单测，不 mock 被测逻辑）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q     # 单元 / 接口测试
python -m eval.run_all 5                           # 检索评测(Recall@5/MRR) + 生成评测
```
