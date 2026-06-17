# Changelog

## v0.1.0 (2026-06-14)

### Step 0: 项目基础骨架

- 项目目录结构搭建（frontend / backend / agents / prompts / strategies / execution / knowledge）
- Python 3.9 venv + FastAPI + Uvicorn + SQLAlchemy + ChromaDB
- Next.js 15 + React 19 + TailwindCSS 4 前端
- 9 张 SQLite 表自动创建 (stock_daily / stock_pick / positions / trade_logs / review_logs / knowledge_docs / agent_memory / strategy_result / system_config)
- ChromaDB 向量库初始化 (knowledge + agent_memory)
- LLM Adapter 多模型适配器 (Claude / GPT / DeepSeek / GLM / Gemini 接口)
- DeepSeek 配置并验证通过

### Step 1: AI Chat

- FastAPI `/api/chat/stream` SSE 流式对话端点
- ChatGPT 风格浅色主题聊天界面
- JSON 编码 SSE 传输（修复换行符丢失 bug）
- `marked` + `DOMPurify` Markdown 渲染（替代 react-markdown，解决 React 19 兼容）
- 页面间导航栏互联

### Step 2: 市场数据 + 情绪 Agent

- AKShare 数据采集服务 (涨停池 / 板块排名 / 市场宽度)
- `EmotionAgent` — 市场情绪六阶段分析 (冰点→修复→分歧→一致→高潮→退潮)
- `prompts/emotion.md` 提示词模板
- 30s 内存缓存机制（避免重复 AKShare 慢调用）
- 市场 Dashboard 页面 (`/dashboard`)
- 涨停板龙虎榜表格
- 慢速 API 从 Dashboard 摘要中分离（44s → 3s）

### Step 3: 多 Agent 管道 + 选股

- `SectorAgent` — 板块轮动分析（主线/轮动/资金流向）
- `StockPickerAgent` — 涨停池选股推荐（评分/买点/止损/目标/仓位）
- `StrategyScoringCenter` — 3 Agent 编排引擎
- 异步任务管理器（后台线程 + task_id 轮询）
- 策略评分权重体系
- Dashboard 升级支持全部分析展示

### Step 4: 威科夫 + 风控 + RAG

- `WyckoffAgent` — 威科夫结构分析（RAG 增强）
- `RiskAgent` — 风险控制（熔断/限制/警告/仓位覆盖）
- 知识库文件创建（威科夫理论 / 缩写词典 / 情绪周期）
- ChromaDB RAG 摄取 + 检索模块
- `backend/rag.py` — 知识库管理（`--ingest` / `--query`）
- 5 Agent 完整管道编排（评分中心升级）
- Dashboard 展示威科夫信号 + 风控面板

### Step 5: 持仓管理 + 复盘

- 持仓 CRUD API (`/api/positions/`)
- AI 持仓分析（持有/减仓/止盈/清仓）
- 持仓管理页面 (`/positions`)
- 自动盈亏计算 + 交易日志记录
- AI 复盘中 API (`/api/reviews/`)
- 复盘统计 + 策略胜率计算 + 历史记录
- 复盘中页面 (`/reviews`)

### Step 6: 执行层 + 飞书集成

- `execution/` 模块 — 抽象执行器 + Mock 模式 + RPA 骨架
- 交易执行 API (`/api/execute/buy` / `sell`)
- Dashboard 选股表增加「执行」按钮
- 飞书 Bitable 集成 (`/api/feishu/`)
- 交易计划自动同步到飞书多维表格
- 复盘报告同步到飞书多维表格
- `ARCHITECTURE.md` 完整信息架构图
- `USAGE.md` 使用指南
