# RedDream API · Postman 测试指南

## 快速开始

### 1. 启动 RedDream 服务

```bash
cd E:\ReshapingMyself\projects\RedDream
.venv\Scripts\python.exe -m uvicorn web.server:app --host 127.0.0.1 --port 7860
```

确认服务启动：浏览器访问 http://127.0.0.1:7860/api/health

### 2. 导入集合

Postman → Import → 选择 `RedDream_API.postman_collection.json`

### 3. 配置变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `baseUrl` | `http://127.0.0.1:7860` | 服务地址 |
| `adminToken` | 空 | 管理后台 Bearer Token（对应 .env 中的 ADMIN_TOKEN） |
| `userToken` | 自动填充 | 调用「用户登录」后自动填入 |

### 4. 执行顺序

按文件夹编号从 0 到 5 顺次执行：

```
0. 基础接口        → 先确认服务正常
1. 核心问答        → 测 SSE 流式回答
2. 用户认证        → 注册 → 登录 → 获取用户信息
3. 管理后台        → 需要先设置 adminToken
4. 图谱探索        → 关系图 / 路径搜索 / 邻居网络
5. 书籍切换        → 多书切换 + 异常输入校验
```

## 面试常见操作展示

### 场景1：测一个接口的完整流程

以 `/api/admin/retriever` 为例：

```
1. GET  → 读当前值         → 验证返回 {mode, label}
2. POST → 切换到 keyword   → 验证 ok:true, mode:"keyword"
3. GET  → 确认切换生效     → 验证 mode 已变为 "keyword"
4. POST → 切回 vector      → 恢复原始状态
```

### 场景2：SSE 流式接口测试

`/api/ask` 返回 `text/event-stream`，Postman 会逐行展示。

**验证点**：
- Content-Type 含 `text/event-stream`
- 每行以 `data:` 开头
- 包含 `__ROUTE__`（路由元数据）、`__SOURCES__`（引用来源）、`__GRAPH__`（图谱数据）
- 流最终以 `[DONE]` 或自然结束

**面试 checklist**：
- [ ] 空问题 → 提示 "请输入问题"
- [ ] 纯空白 → 同上
- [ ] 正常问题 → 返回检索提示 + 回答文本
- [ ] 多轮对话 → 带 history 的指代消解
- [ ] Agent 模式 → 返回工具调用结果

### 场景3：鉴权 + 参数校验

**无 Token 访问管理接口**：
```
GET /api/admin/status → 401 Unauthorized （或开发期跳过鉴权）
```

**参数边界值**：
```
POST /api/admin/topk  {"top_k": 0}   → 拒绝（范围 1-20）
POST /api/admin/topk  {"top_k": 25}  → 拒绝
POST /api/admin/topk  {"top_k": 5}   → 成功
```

## 与 pytest 测试的对照

| Postman 测试 | pytest 对应测试 |
|-------------|----------------|
| 健康检查 | `test_api_health.py::TestHealthEndpoint` |
| 空问题校验 | `test_api_ask.py::TestAskInputValidation` |
| SSE 格式 | `test_api_ask.py::TestAskSSEFormat` |
| 管理后台鉴权 | `test_api_admin.py::TestAdminAuth` |
| Top-K 边界值 | `test_api_admin.py::TestTopKConfig` |
| 领域切换 | `test_api_domains.py::TestSwitchDomain` |

## 一键跑全部

Postman Collection Runner：
1. 点击集合名称右侧的 ▶ Run
2. 选择 "Run manually"
3. 数据文件选 `_postman_data.json`（如有）
4. 勾选 "Save responses"
5. 点击 Run

会看到每个请求的状态码、响应时间、test script 断言结果。
