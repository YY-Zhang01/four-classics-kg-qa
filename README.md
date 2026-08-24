# 红楼梦企业级问答系统

一个从零搭建的企业级智能问答系统，已演进到 **KG+向量融合检索 + Web 可视化** 阶段。

## 当前阶段：P2（知识图谱融合 + ECharts 可视化）

全链路：`PDF → MinerU 解析 → 切块 → 向量化 → 向量/关键词/KG 三模检索 → 大模型受控生成 → Web 流式推送`

## 核心能力

| 能力 | 说明 |
|------|------|
| **三模检索** | 关键词 / 语义向量 / KG+向量融合，运行时可热切换 |
| **知识图谱** | 人物关系+属性三元组（56条），关系型问题自动走 KG 检索 |
| **ECharts 可视化** | 人物关系力导向图，可拖拽、缩放、折叠 |
| **SSE 流式** | 回答逐字推送，图谱+原文引用数据同步返回 |
| **双角色 Web** | 用户聊天界面 + 管理后台（日志/统计/检索切换/Top-K/CSV导出） |
| **多轮对话** | 代词消解+上下文感知，连续追问无需重复主语 |
| **原文引用** | 每轮回答可展开查看参考原文片段 |
| **企业级底线** | 可溯源（出处标注）、不编造（无资料不调模型）、可审计（日志+导出） |

## 目录结构

```
config/         全局配置（模型/检索/数据库），密钥走 .env
pdfs/           原始 PDF（自备红楼梦 PDF 放这里）
parsed/         MinerU 解析出的 Markdown
chunks/         切块后的 JSON（带出处）
parser/         MinerU 解析封装
kb_builder/     切块
retrieval/      检索（关键词 / 向量 / KG融合 / 检索器工厂）
kg/             知识图谱（Schema / 抽取 / 存储）
llm/            大模型可插拔接入层 + embedding
prompts/        提示词（与代码分离）
core/           受控生成（拼上下文、流式、溯源）
web/            FastAPI 服务端 + HTML 前端
scripts/        工具脚本（灌库/建表/连通性测试/种子数据）
logs/           审计日志
eval/           评测（后续阶段）
```

## 快速开始

```powershell
# 1. 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 2. 装依赖
pip install -r requirements.txt

# 3. 配置：复制模板并填入本地信息
copy config\.env.example .env

# 4. 确保 PostgreSQL 在运行，创建数据库和账号
psql -U postgres -f scripts\db_schema.sql

# 5. 放一份红楼梦 PDF 到 pdfs\，然后跑通解析+切块
python -m parser.run_mineru
python -m kb_builder.split

# 6. 向量化入库
python -m scripts.ingest_db

# 7. 灌入知识图谱种子数据
python -m scripts.seed_kg

# 8. 启动 Web 服务
python -m web.server
# 用户页面  http://127.0.0.1:7860
# 管理后台  http://127.0.0.1:7860/admin
```

## 检索方式

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `keyword` | jieba 分词 + 关键词共现 | P0 兜底 |
| `vector` | bge-m3 语义向量 + 余弦相似度 | 模糊语义查询 |
| `fusion` | KG 结构化事实 + 向量原文块，双路融合 | 关系型问题优先 |

在管理后台或通过 `.env` 的 `RETRIEVER` 字段切换（运行时可热切）。

## 红线（企业级底线）

- **可溯源**：每个回答都带【出处：来源·章节】。
- **不编造**：检索不到就答"未找到"，绝不脑补。
- **可审计**：每次问答写入 `logs/qa_audit.jsonl`。
