# AI Trading OS - Database models (SQLite via SQLAlchemy)
import datetime
from sqlalchemy import String, Float, Integer, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class StockDaily(Base):
    """每日行情数据"""
    __tablename__ = "stock_daily"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    name: Mapped[str] = mapped_column(String(32))
    trade_date: Mapped[datetime.date] = mapped_column(index=True)
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    close: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    turnover_rate: Mapped[float] = mapped_column(Float, default=0.0)
    create_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)


class StockPick(Base):
    """AI 推荐股票 — candidate pool with lifecycle tracking"""
    __tablename__ = "stock_pick"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime.date] = mapped_column(index=True)
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    buy_price: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float, default=0.0)
    target_price: Mapped[float] = mapped_column(Float, default=0.0)
    position_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    agent_result: Mapped[str] = mapped_column(Text, default="")  # JSON: per-agent scores
    # Legacy status — kept for backward compat; candidate_status is the new field
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | confirmed | executed | ignored
    # ── V1.5 candidate pool lifecycle ──
    candidate_status: Mapped[str] = mapped_column(
        String(24), default="pending",
        comment="night_screened | morning_calibrated | confirmed | active | executed | expired | abandoned"
    )
    pool_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    screening_strategy: Mapped[str] = mapped_column(String(32), default="")
    night_score: Mapped[float] = mapped_column(Float, default=0.0)
    morning_score: Mapped[float] = mapped_column(Float, default=0.0)
    market_open_price: Mapped[float] = mapped_column(Float, default=0.0)
    actual_entry_price: Mapped[float] = mapped_column(Float, nullable=True)
    delta_from_screen: Mapped[float] = mapped_column(Float, default=0.0)
    create_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    expire_time: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)


class CandidatePool(Base):
    """候选池批次记录 — tracks each screening run"""
    __tablename__ = "candidate_pool"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pool_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    trade_date: Mapped[datetime.date] = mapped_column(index=True)
    stage: Mapped[str] = mapped_column(String(20), comment="night_screen | morning_calibrate | llm_confirm")
    total_screened: Mapped[int] = mapped_column(Integer, default=0)
    total_qualified: Mapped[int] = mapped_column(Integer, default=0)
    strategies_used: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    market_snapshot: Mapped[str] = mapped_column(Text, default="{}")   # JSON
    overnight_changes: Mapped[str] = mapped_column(Text, default="{}") # JSON, only for morning_calibrate
    create_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)


class Position(Base):
    """当前持仓"""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(32))
    buy_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    profit_rate: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="holding")  # holding | closed
    buy_time: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    sell_time: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)


class TradeLog(Base):
    """交易记录"""
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(10))  # buy | sell
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    agent_decision: Mapped[str] = mapped_column(Text, default="")
    execute_result: Mapped[str] = mapped_column(String(20), default="success")
    create_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)


class ReviewLog(Base):
    """AI 复盘"""
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime.date] = mapped_column(index=True)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    loss: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    mistakes: Mapped[str] = mapped_column(Text, default="")
    suggestions: Mapped[str] = mapped_column(Text, default="")


class KnowledgeDoc(Base):
    """知识库文档"""
    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50))  # wyckoff | serenity | personal | ai_summary
    tags: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text)
    embedding_status: Mapped[bool] = mapped_column(Boolean, default=False)
    create_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)


class AgentMemory(Base):
    """Agent 长期记忆"""
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    memory_type: Mapped[str] = mapped_column(String(50))  # observation | insight | pattern
    content: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)  # confidence/importance
    update_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)


class StrategyResult(Base):
    """策略统计"""
    __tablename__ = "strategy_result"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(50))
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_profit: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    update_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)


class MarketSnapshot(Base):
    """盘中市场快照 — 每30秒记录一次"""
    __tablename__ = "market_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime.date] = mapped_column(index=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(index=True)
    session: Mapped[str] = mapped_column(String(20))  # morning | afternoon
    limit_up_count: Mapped[int] = mapped_column(Integer, default=0)
    limit_down_count: Mapped[int] = mapped_column(Integer, default=0)
    up_down_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    breadth_data: Mapped[str] = mapped_column(Text, default="{}")   # JSON
    top_sectors: Mapped[str] = mapped_column(Text, default="[]")    # JSON
    candidate_status: Mapped[str] = mapped_column(Text, default="{}")  # JSON: candidate pool status


class SystemConfig(Base):
    """系统配置"""
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(100), unique=True)
    config_value: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(String(255), default="")
