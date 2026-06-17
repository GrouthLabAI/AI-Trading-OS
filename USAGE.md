# AI Trading OS 使用指南

## 一、系统简介

AI Trading OS 是一个运行在本地电脑上的 **AI 半自动操盘系统**。

**核心理念：** AI 分析 → 人决策 → 机器执行

**当前版本：** V0.1（Step 1：AI Chat 已可用，后续功能逐步开发中）

---

## 二、启动系统

### 前置条件

- Python 3.9+
- Node.js 24+
- DeepSeek API Key（或其他 LLM 的 Key）

### 第一次使用

```bash
# 1. 进入项目目录
cd AI-trading

# 2. 创建 Python 虚拟环境并安装依赖（仅首次）
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. 安装前端依赖（仅首次）
cd frontend && npm install --registry=https://registry.npmjs.org && cd ..

# 4. 配置 API Key（仅首次）
cp .env.example .env
# 编辑 .env 文件，设置：
#   LLM_PROVIDER=deepseek    （或其他：claude | gpt | glm）
#   DEEPSEEK_API_KEY=你的key
```

### 日常启动

打开两个终端窗口：

**终端 1 — 启动后端（端口 8000）：**
```bash
cd AI-trading
./venv/bin/python -m uvicorn backend.main:app --reload
```

**终端 2 — 启动前端（端口 3000）：**
```bash
cd AI-trading/frontend
npm run dev
```

然后浏览器打开 **http://localhost:3000**

---

## 三、AI Chat 使用指南

这是当前已实现的核心功能——一个类似 ChatGPT 的交易助手对话界面。

### 3.1 界面布局

```
┌────────────────────────────────┐
│ 🤖 AI Trading OS               │  ← 顶部标题栏
│ AI 交易助手                      │
├────────────────────────────────┤
│                                │
│  [对话历史区域]                   │  ← 中间消息区
│  用户消息（绿色气泡）              │
│  AI 回复（深色气泡，支持 Markdown） │
│                                │
├────────────────────────────────┤
│ [输入框________________] [发送] │  ← 底部输入区
└────────────────────────────────┘
```

### 3.2 操作方式

| 操作 | 方式 |
|------|------|
| 发送消息 | 输入文字后按 **Enter** 或点击发送按钮 |
| 换行 | **Shift + Enter** |
| 查看历史 | 滚动消息区域 |

### 3.3 对话示例

你可以用自然语言问任何交易相关的问题：

**市场分析类：**
```
今天A股市场情绪怎么样？
最近哪个板块最强？
帮我分析一下当前市场的风险。
```

**技术分析类：**
```
什么是威科夫理论中的 SOS？
如何识别 Spring 形态？
解释一下 LPS 和 LPSY 的区别。
```

**策略讨论类：**
```
首板战法和龙头低吸各有什么优缺点？
退潮期应该怎么操作？
如何控制仓位风险？
```

**知识学习类：**
```
介绍一下情绪周期的六个阶段。
2进3板的核心逻辑是什么？
serenity 交易思想的核心是什么？
```

### 3.4 Markdown 渲染支持

AI 回复支持完整的 Markdown 格式，包括：

- **标题**（h1~h3）
- **列表**（有序/无序）
- **代码块**（行内代码 + 多行代码块）
- **引用块**（绿色左边框）
- **表格**
- **粗体** / *斜体*
- **链接**

---

## 四、API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 系统健康检查 |
| `/api/chat/` | POST | 非流式对话（返回完整回复） |
| `/api/chat/stream` | POST | 流式对话（逐字返回，前端使用） |

### 调用示例

```bash
# 健康检查
curl http://localhost:8000/api/health

# 发送对话（非流式）
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "什么是威科夫理论？", "history": []}'
```

---

## 五、切换 LLM 模型

编辑 `.env` 文件中的 `LLM_PROVIDER` 即可切换：

| 值 | 模型 | 需要设置的 Key |
|----|------|---------------|
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` |
| `claude` | Anthropic Claude | `ANTHROPIC_API_KEY` |
| `gpt` | OpenAI GPT-4o | `OPENAI_API_KEY` |
| `glm` | 智谱 GLM-4 | `OPENAI_API_KEY`（复用） |

切换后重启后端即可生效。

---

## 六、当前功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| AI Chat（自然语言对话） | ✅ 已可用 | 支持流式输出 + Markdown 渲染 |
| 多模型切换 | ✅ 已可用 | DeepSeek / Claude / GPT / GLM |
| SQLite 数据库 | ✅ 已就绪 | 9 张表自动创建，数据采集后进行填充 |
| ChromaDB 向量库 | ✅ 已就绪 | knowledge + agent_memory 集合已创建 |
| 行情数据采集 | 🔜 下一步 | AKShare / 东方财富接入 |
| AI 多 Agent 分析 | 🔜 计划中 | 情绪/板块/选股/威科夫/仓位/风控 |
| 策略评分中心 | 🔜 计划中 | 6 Agent 加权评分 |
| 持仓管理 | 🔜 计划中 | 盈亏监控 + AI 建议 |
| AI 自动复盘 | 🔜 计划中 | 日报/周报/月报/策略统计 |
| RPA 模拟盘执行 | 🔜 计划中 | 东方财富模拟盘自动交易 |

---

## 七、目录结构速查

```
AI-trading/
├── .env                 # 你的 API Key 配置（不要提交到 Git）
├── backend/             # Python FastAPI 后端
│   ├── main.py          #   应用入口
│   ├── chat.py          #   Chat API
│   ├── llm_adapter.py   #   多模型适配器
│   ├── models.py        #   数据库表定义
│   ├── database.py      #   数据库连接
│   └── vector_store.py  #   ChromaDB 向量库
├── frontend/            # Next.js 前端
│   └── src/app/
│       └── page.tsx     #   AI Chat 页面
├── docs/                # 设计文档
└── CLAUDE.md            # 开发者参考文档
```
