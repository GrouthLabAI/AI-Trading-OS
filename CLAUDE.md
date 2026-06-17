# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend (Python 3.9+, requires venv)
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (Node 24+)
cd frontend && npm install --registry=https://registry.npmjs.org && npm run dev

# One-liner: start both
./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
cd frontend && npm run dev
```

**Note:** Python 3.9 does not support `match`/`case` or `X | None` union syntax. Use `if/elif` and `Optional[X]` from `typing`. `list[dict]` type hints work (PEP 585).

## Project Overview

AI Trading OS is a **personal AI trading operating system** that can learn, think, execute, review, and grow. It is NOT a stock-picking tool or quant bot — it is a sustainable, iterable AI Agent product.

**Three design principles:**

| Principle | Role | Scope |
|-----------|------|-------|
| AI 分析 (Analyze) | Market sentiment, sector rotation, Wyckoff structure, leader identification, position sizing, risk control | Data → Insight |
| 人 决策 (Decide) | Review AI recommendations with full reasoning (why this stock, why this score, why this position size) | Insight → Decision |
| 机器 执行 (Execute) | RPA → East Money paper trading → auto input → auto confirm → auto screenshot → auto record | Decision → Action |

**Core competitive advantage** (the real moat):
```
交易知识库 + AI推理能力 + 个人交易数据 + 长期复盘 + Agent记忆
                    ↓
        优秀交易员思想 + 威科夫理论 + 你自己的交易经验 + AI持续学习
                    ↓
            Personal AI Trading Brain（个人AI交易大脑）
```

The project is currently in planning phase. All design documents are in `docs/`.

## Architecture

```
Next.js Dashboard (Web UI)
        │ REST / WebSocket
        ▼
FastAPI Backend (API + Agent orchestration)
        │
   ┌────┼────────────┐
   ▼    ▼            ▼
Data   Agent        Task
Svc    Center       Scheduler
   │    │            │
   ▼    ▼            ▼
SQLite ChromaDB   Cron Jobs
        │
        ▼
Human Confirm (manual step — NO auto-trading)
        │
        ▼
Local Executor (PyAutoGUI + OpenCV + PaddleOCR)
        │
        ▼
东方财富模拟盘 (East Money paper trading)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js (App Router) + TailwindCSS + shadcn/ui |
| Backend API | FastAPI (Python) |
| AI Orchestration | LangGraph |
| LLM Adapter | Unified interface supporting Claude / GPT / DeepSeek / GLM / Gemini |
| Relational DB | SQLite (V1), PostgreSQL (V2) |
| Vector DB | ChromaDB |
| Data Sources | AKShare, East Money public APIs, pywencai |
| RPA Execution | PyAutoGUI, OpenCV, PaddleOCR (screen OCR for trade confirmation) |
| Notifications | macOS native, Bark, Telegram, 企业微信 |

## Multi-Agent System

Six specialized agents feed into a Strategy Scoring Center, which produces weighted recommendations:

| Agent | Responsibility | Scoring Weight |
|-------|---------------|----------------|
| EmotionAgent | Market sentiment (冰点→高潮→退潮 cycle) | 20% |
| SectorRotationAgent | Sector strength, capital flows | 20% |
| WyckoffAgent | Wyckoff structure (SOS, SOW, Spring, UT, LPS, LPSY) | 20% |
| StockPickerAgent | Scans all A-shares, outputs candidates | 15% (龙头地位) |
| PositionAgent | Suggests position size (10%/20%/30%/空仓) | 10% (成交量) |
| RiskAgent | Consecutive loss circuit breaker, chasing-prevention | 15% |

Agents use RAG against the personal knowledge base (Wyckoff theory, serenity methodology, personal trade journals) stored in ChromaDB.

## Claude Code Development Standards (from V1.1)

These rules govern how Claude Code should write and organize code in this project:

**1. One agent, one responsibility** — Each agent file does exactly one thing:
- `emotion_agent.py` only analyzes market sentiment (NOT stock picking, NOT order placement)
- Each agent is independently testable and replaceable

**2. Prompts are independent files** — Agent prompt templates live in `prompts/` as separate `.md` files:
- `prompts/emotion.md`, `prompts/wyckoff.md`, `prompts/stock_pick.md`, `prompts/review.md`
- This allows prompt iteration without touching agent code
- `prompts/` should be established before writing agent logic

**3. Strategies are independent** — Trading strategies in `strategies/` are standalone modules:
- `strategies/wyckoff.py`, `strategies/dragon.py`, `strategies/first_board.py`, `strategies/low_absorb.py`
- Strategies can be swapped, combined, or A/B tested without changing other code

**4. Execution is independent** — The RPA layer in `execution/` knows nothing about AI:
- `execution/rpa.py`, `execution/ocr.py`, `execution/trade_executor.py`
- If the brokerage platform changes, only this layer changes — AI agents are unaffected

## Database (SQLite, 8 tables)

- `stock_daily` — OHLCV + turnover per stock per day
- `stock_pick` — AI recommendations with scores, entry/stop/target prices
- `positions` — current holdings with P&L tracking
- `trade_logs` — executed trades with agent decision audit trail
- `review_logs` — daily/weekly/monthly AI-generated reviews
- `knowledge_docs` — knowledge base documents with embedding status
- `agent_memory` — long-term agent memory with confidence scores
- `strategy_result` — per-strategy performance stats (win rate, Sharpe, max drawdown)
- `system_config` — key-value config store

## Development Phases

### V1.0 execution order (revised per V1.1 — highest success rate for solo developer)

The order matters. Each step builds on the previous one:

```
Step 1: AI Chat (like ChatGPT)        ← start here, validate LLM integration
        ↓
Step 2: AI Market Analysis            ← add data → insight pipeline
        ↓
Step 3: AI Stock Picking              ← add candidate generation + scoring
        ↓
Step 4: AI Position Management        ← add holdings tracking + alerts
        ↓
Step 5: AI Auto Review                ← add daily/weekly/monthly reporting
        ↓
Step 6: RPA → East Money Paper Trading ← add execution LAST (most fragile layer)
        ↓
Step 7: Complete Closed Loop          ← learn → analyze → decide → execute → review → learn
```

### Weekly breakdown (from `docs/Claude Code 开发任务拆解.docx`)

1. **Week 1** — Project scaffold: FastAPI, Next.js, SQLite, ChromaDB, Claude Code config
2. **Week 2** — Data pipeline: AKShare, East Money, sector/limit-up/limit-down, capital flow → SQLite
3. **Week 3** — AI Agents: all 6 agents + Strategy Scoring Center
4. **Week 4** — Dashboard: market cockpit, AI chat, stock pick page, positions, review pages
5. **Week 5+** — Knowledge base: ingest Wyckoff/serenity docs, RAG retrieval
6. **Week 6+** — Paper trading execution: RPA on East Money simulation, OCR confirmation
7. **Week 7+** — Auto-review: daily/weekly/monthly reports, strategy win-rate stats
8. **Week 8** — V1.0 release: integration testing, paper trading validation

### Version roadmap

| Version | Scope |
|---------|-------|
| V1 | AI stock recommendations + manual trading + Dashboard |
| V2 | RPA paper trading auto-execution on East Money |
| V3 | Position monitoring + AI sell alerts + auto review |
| V4 | Strategy statistics + agent long-term memory + auto learning |
| V5 | Multi-strategy switching + multi-agent collaboration |
| V6 | Full Personal AI Trading Brain — continuous self-optimization |

**V1.0 MVP checklist:**
- ✅ AI market analysis, stock picking, AI chat, human confirmation
- ✅ East Money paper trading execution, auto trade logging, auto review
- ❌ Real-money trading, high-frequency quant, unattended trading, multi-account

## Key Design Decisions

1. **V1 starts with AI Chat, not auto-trading** — The first deliverable is a ChatGPT-like interface for market Q&A. This validates LLM integration early and builds the reasoning layer before touching the fragile RPA layer. RPA execution is added last (Step 6 of 7). This maximizes success rate for a solo developer.

2. **RPA over API for execution** — East Money's simulation platform has no public API. The executor uses screen automation (PyAutoGUI clicks) with OCR (PaddleOCR) to confirm fills. This layer must be fully isolated from AI logic so a platform change requires no agent changes.

3. **Human-in-the-loop is mandatory** — The system must never place trades without explicit human confirmation. The Decision Center enforces this gate. Every recommendation includes full reasoning (why this stock, why this score, why this position size).

4. **Knowledge base is the real moat** — It starts with imported Wyckoff/serenity documents but grows continuously from AI-generated trade summaries and personal journal entries. The RAG pipeline must handle incremental updates. The combination of trading knowledge + AI reasoning + personal trade data + long-term review creates the Personal AI Trading Brain.

5. **Strategy scoring uses weighted summation** — Not a black-box model. Every recommendation is explainable: which agents contributed what score and why.

6. **LLM Adapter pattern** — All agent LLM calls go through a unified adapter interface. This allows switching between Claude, GPT, DeepSeek, GLM, and Gemini without changing agent logic. V1 uses Claude, but the adapter must be designed for swappability from day one.

## Project Directory Structure (planned, from V1.1)

```
AI-Trading-OS/
├── docs/               # Design documents (planning phase artifacts)
├── frontend/           # Next.js + TailwindCSS + shadcn/ui dashboard
├── backend/            # FastAPI application
├── agents/             # AI agent implementations (one agent = one file)
│   ├── emotion_agent.py
│   ├── stock_picker.py
│   ├── wyckoff_agent.py
│   ├── position_agent.py
│   ├── risk_agent.py
│   └── review_agent.py
├── prompts/            # Independent prompt templates (.md files)
│   ├── emotion.md
│   ├── wyckoff.md
│   ├── stock_pick.md
│   └── review.md
├── strategies/         # Standalone strategy modules (swappable)
│   ├── wyckoff.py
│   ├── dragon.py
│   ├── first_board.py
│   └── low_absorb.py
├── execution/          # RPA execution layer (AI-free zone)
│   ├── rpa.py
│   ├── ocr.py
│   └── trade_executor.py
├── knowledge/          # Markdown knowledge base files (the moat)
├── database/           # SQLite schema and migrations
├── vector_db/          # ChromaDB persistence
├── scheduler/          # Cron-style task scheduling
├── logs/               # Runtime logs
├── reviews/            # Generated review reports
├── tests/              # Test suite
└── main.py             # Entry point
```

## Knowledge Base Structure (from V1.1)

This is the project's most valuable long-term asset. The knowledge base combines external trading theory with personal experience:

```
knowledge/
├── 威科夫理论.md        # Wyckoff Theory (SOS, SOW, Spring, UT, LPS, LPSY)
├── 威科夫缩写.md        # Wyckoff abbreviation dictionary
├── 情绪周期.md          # Market sentiment cycle
├── 龙头战法.md          # Leader stock methodology
├── 首板.md              # First board strategy
├── 1进2.md              # 1→2 board progression
├── 2进3.md              # 2→3 board progression
├── serenity.md          # Serenity trading philosophy
├── 自己复盘.md          # Personal trade reviews
└── AI总结.md            # AI-generated insights
```

## Current State

| Step | Status | Description |
|------|--------|-------------|
| Step 1: AI Chat | ✅ Complete | Chat UI (ChatGPT light theme) + SSE streaming + Markdown |
| Step 2: Market Analysis | ✅ Complete | AKShare data + EmotionAgent + Dashboard |
| Step 3: Multi-Agent Pipeline | ✅ Complete | SectorAgent + StockPickerAgent + ScoringCenter + Async task manager |

### Implemented modules

| Component | Path | Purpose |
|-----------|------|---------|
| Data Service | `backend/data_service.py` | AKShare: spot, sectors, limit-up pool; 30s in-memory cache |
| Emotion Agent | `agents/emotion_agent.py` + `prompts/emotion.md` | Market sentiment cycle (冰点→退潮) |
| Sector Agent | `agents/sector_agent.py` + `prompts/sector.md` | Sector rotation analysis (主线/轮动/资金流向) |
| Stock Picker | `agents/stock_picker.py` + `prompts/stock_pick.md` | Limit-up pool scoring (买点/止损/目标/仓位) |
| Scoring Center | `strategies/scoring.py` | Orchestrates 3 agents sequentially |
| Task Manager | `backend/task_manager.py` | Background async tasks (thread-based) |
| Market API | `backend/market.py` | `/summary`, `/analyze`, `/analyze/{id}`, `/emotion`, `/sectors`, `/limit-ups` |
| Dashboard | `frontend/src/app/dashboard/` | Cards + async AI analysis panel + stock picks table |

### API endpoints

| Endpoint | Method | Time | Description |
|----------|--------|------|-------------|
| `/api/chat/stream` | POST | streaming | AI Chat (SSE JSON-encoded) |
| `/api/market/summary` | GET | ~3s | Breadth + limit-ups |
| `/api/market/limit-ups` | GET | ~3s | Limit-up pool |
| `/api/market/emotion` | GET | ~10s | Emotion agent only |
| `/api/market/analyze` | GET | <1s (returns task_id) | Start full 3-agent pipeline |
| `/api/market/analyze/{id}` | GET | <1s (poll) | Check pipeline status/result |

### Key technical notes

- **Python 3.9**: No `match`/`case`, no `X \| None` — use `if/elif` and `Optional[X]`
- **SSE**: Tokens JSON-encoded to preserve `\n` through SSE transport
- **Markdown**: `marked` + `DOMPurify` (not `react-markdown`, conflicts with React 19)
- **AKShare**: Live data only during trading hours (Mon-Fri 9:30-15:00 CST). Weekend: limit-up pool returns last trading day
- **Slow endpoints**: `stock_zh_a_spot_em` (~40s) and `stock_board_concept_spot_em` (~15s) gated behind separate endpoints; summary uses only fast limit-up pool (~3s)
- **Long-running tasks**: `/analyze` uses async task pattern — returns task_id immediately, frontend polls every 2s
- **npm registry**: Use `--registry=https://registry.npmjs.org` when internal registry unavailable

**Next step:** Step 4 — Wyckoff Agent + Risk Agent + Knowledge Base RAG integration
