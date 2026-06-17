#!/usr/bin/env python3
"""
威科夫 K线图生成工具 — 自动拉取数据 + 检测事件 + 标注图表

用法:
    python scripts/kline_chart.py --code 002636
    python scripts/kline_chart.py --code 002636 --name 金安国纪 --days 120
    python scripts/kline_chart.py --code 002636 --period weekly

事件检测:
    自动识别 SOS / SOW / Spring / UT / LPS / JOC / BC 七种威科夫事件
    标注直接显示在K线图上（文字标签，非图标标记）

输出:
    1920×1080, 150 DPI PNG, 保存到 charts/ 目录
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Project root ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART_DIR = PROJECT_ROOT / "charts"
CHART_DIR.mkdir(exist_ok=True)


# ── Data fetching ───────────────────────────────────────────────────

def fetch_kline(code: str, days: int = 120, period: str = "daily") -> pd.DataFrame:
    """Fetch historical K-line data via AKShare (tries multiple APIs)."""
    try:
        import akshare as ak
    except ImportError:
        print("请安装 AKShare: pip install akshare")
        sys.exit(1)

    # Determine market prefix
    if code.startswith(("60", "68")):
        symbol = f"sh{code}"
    else:
        symbol = f"sz{code}"

    df = None
    period_str = "weekly" if period == "weekly" else "daily"

    # Try 1: stock_zh_a_hist (East Money)
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period=period_str,
                                start_date="20100101",
                                end_date=datetime.date.today().strftime("%Y%m%d"))
    except Exception:
        pass

    # Try 2: stock_zh_a_daily (Sina)
    if df is None or df.empty:
        try:
            if period == "daily":
                df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
        except Exception:
            pass

    # Try 3: stock_zh_a_hist_tx (Tencent)
    if df is None or df.empty:
        try:
            df = ak.stock_zh_a_hist_tx(symbol=code, start_date="20100101",
                                       end_date=datetime.date.today().strftime("%Y%m%d"))
        except Exception:
            pass

    if df is None or df.empty:
        print(f"未获取到 {code} 的K线数据（所有数据源均失败）")
        sys.exit(1)

    # Normalize column names (handle different naming conventions)
    rename_map = {}
    for col in df.columns:
        cl = str(col).lower()
        if "日期" in str(col) or col == "date" or "time" in cl:
            rename_map[col] = "date"
        elif "开盘" in str(col) or col == "open":
            rename_map[col] = "open"
        elif "收盘" in str(col) or col == "close":
            rename_map[col] = "close"
        elif "最高" in str(col) or col == "high":
            rename_map[col] = "high"
        elif "最低" in str(col) or col == "low":
            rename_map[col] = "low"
        elif "成交" in str(col) and "量" in str(col) or col == "volume":
            rename_map[col] = "volume"
        elif "成交" in str(col) and "额" in str(col) or col == "amount":
            rename_map[col] = "amount"
        elif "换手" in str(col) or col == "turnover":
            rename_map[col] = "turnover"

    df = df.rename(columns=rename_map)

    # Ensure required columns exist
    for col in ["date", "open", "close", "high", "low", "volume"]:
        if col not in df.columns:
            print(f"数据缺少必要列: {col}，可用列: {list(df.columns)}")
            sys.exit(1)

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # Ensure numeric
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "close", "high", "low"])

    return df.tail(days)


# ── Wyckoff event detection ─────────────────────────────────────────

def detect_wyckoff_events(df: pd.DataFrame) -> list[dict]:
    """Detect 7 Wyckoff events from OHLCV data. Returns list of {date, event, label}."""

    if len(df) < 20:
        return []

    events = []
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_ = df["open"].values
    volume = df["volume"].values

    # ── Helper: moving average ──
    def ma(arr, n):
        s = np.cumsum(np.insert(arr, 0, 0))
        return (s[n:] - s[:-n]) / n

    vol_ma5 = np.concatenate([volume[:4], ma(volume, 5)])  # pad to same length
    body = close - open_                                      # candle body
    upper_shadow = high - np.maximum(close, open_)
    lower_shadow = np.minimum(close, open_) - low
    spread = high - low                                       # total range
    resistance = ma(high, 20)
    support = ma(low, 20)

    # Pad MAs to full length
    resistance_full = np.concatenate([np.full(19, np.nan), resistance])
    support_full = np.concatenate([np.full(19, np.nan), support])

    # ── Detect events ────────────────────────────────────────────

    for i in range(20, len(df)):
        idx = df.index[i]

        # BC (Buying Climax): 天量阳线 + 上影线长
        if (volume[i] > vol_ma5[i] * 2.0 and body[i] > 0
                and upper_shadow[i] > body[i] * 0.5):
            events.append({"date": idx, "event": "BC", "label": f"BC\n买入高潮"})

        # SOW (Sign of Weakness): 放量阴线 + 宽价差 + 收于低点
        if (volume[i] > vol_ma5[i] * 1.5 and body[i] < 0
                and spread[i] > np.nanmean(spread[max(0, i - 5):i]) * 1.3
                and lower_shadow[i] < abs(body[i]) * 0.3):
            events.append({"date": idx, "event": "SOW", "label": f"SOW\n弱势信号"})

        # UT (Upthrust): 放量 + 突破阻力后跌回 + 上影线长
        if (volume[i] > vol_ma5[i] * 1.3 and not np.isnan(resistance_full[i])
                and high[i] > resistance_full[i] * 1.02
                and close[i] < resistance_full[i]
                and upper_shadow[i] > abs(body[i]) * 1.5):
            events.append({"date": idx, "event": "UT", "label": f"UT\n上冲回落"})

        # Spring: 跌破支撑 + 缩量 + 收回
        if (i >= 2 and not np.isnan(support_full[i])
                and low[i] < support_full[i] * 0.98
                and close[i] > support_full[i]
                and volume[i] < vol_ma5[i] * 1.2
                and close[i] > open_[i]):
            events.append({"date": idx, "event": "Spring", "label": f"Spring\n弹簧效应"})

        # JOC (Jump Across Creek): 放量突破20日高点阻力
        if (i >= 21 and volume[i] > vol_ma5[i] * 1.3
                and close[i] > np.nanmax(high[max(0, i - 20):i])
                and body[i] > 0):
            events.append({"date": idx, "event": "JOC", "label": f"JOC\n跳跃小溪"})

        # SOS (Sign of Strength): 放量阳线 + 延续上涨
        if (volume[i] > vol_ma5[i] * 1.2 and body[i] > 0
                and close[i] > close[i - 1]
                and spread[i] > np.nanmean(spread[max(0, i - 5):i])
                and lower_shadow[i] < body[i] * 0.5):
            events.append({"date": idx, "event": "SOS", "label": f"SOS\n强势信号"})

        # LPS (Last Point of Support): 缩量回调 + 不破支撑 + 小实体
        if (i >= 2 and volume[i] < vol_ma5[i] * 0.6
                and abs(body[i]) < spread[i] * 0.4
                and low[i] > support_full[i]
                and close[i - 1] < close[i]):
            events.append({"date": idx, "event": "LPS", "label": f"LPS\n最后支撑"})

    # ── Deduplicate: keep strongest signal per day ────────────────
    priority = {"Spring": 1, "JOC": 2, "SOS": 3, "BC": 4, "LPS": 5, "UT": 6, "SOW": 7}
    seen_dates = {}
    filtered = []
    for e in events:
        d = e["date"]
        if d not in seen_dates or priority.get(e["event"], 99) < priority.get(seen_dates[d], 99):
            seen_dates[d] = e["event"]
    for e in events:
        if seen_dates.get(e["date"]) == e["event"]:
            if e["date"] not in [f["date"] for f in filtered]:
                filtered.append(e)

    return filtered


# ── Chart rendering ─────────────────────────────────────────────────

def render_chart(df: pd.DataFrame, events: list[dict], code: str, name: str):
    """Render K-line chart with Wyckoff event annotations."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
        import matplotlib.dates as mdates
    except ImportError:
        print("请安装 matplotlib: pip install matplotlib")
        sys.exit(1)

    # ── Chinese font setup ───────────────────────────────────────
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC",
                                        "Heiti SC", "STHeiti", "SimHei", "WenQuanYi Micro Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    # ── Color palette (China style: 红涨绿跌) ─────────────────────
    RED = "#dc143c"
    GREEN = "#228b22"
    BG = "#1a1a2e"
    GRID = "#2a2a4a"
    TEXT = "#e0e0e0"
    UP_COLOR = RED
    DOWN_COLOR = GREEN

    # ── Prepare data ─────────────────────────────────────────────
    dates = df.index
    # Convert to matplotlib date numbers
    date_nums = mdates.date2num(dates.to_pydatetime())

    close = df["close"].values
    open_ = df["open"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    up = close >= open_
    down = close < open_

    # ── Moving averages ──────────────────────────────────────────
    ma5 = np.concatenate([np.full(4, np.nan), np.convolve(close, np.ones(5) / 5, mode="valid")])
    ma10 = np.concatenate([np.full(9, np.nan), np.convolve(close, np.ones(10) / 10, mode="valid")])
    ma20 = np.concatenate([np.full(19, np.nan), np.convolve(close, np.ones(20) / 20, mode="valid")])

    # ── Figure ───────────────────────────────────────────────────
    fig = plt.figure(figsize=(20, 10), dpi=150)
    fig.patch.set_facecolor(BG)

    # Create two panels: main chart (70%) + volume (30%)
    gs = fig.add_gridspec(2, 1, height_ratios=[7, 3], hspace=0.05)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)

    ax1.set_facecolor(BG)
    ax2.set_facecolor(BG)

    # ── Panel 1: K-line (candlestick) ────────────────────────────
    body_width = max(0.6, 0.8 * np.median(np.diff(date_nums)) if len(date_nums) > 1 else 0.8)

    for i in range(len(df)):
        # Candle body
        o, c, h, l = open_[i], close[i], high[i], low[i]
        color = UP_COLOR if c >= o else DOWN_COLOR
        body_h = abs(c - o)

        # Wick (high-low line)
        ax1.plot([date_nums[i], date_nums[i]], [l, h], color=color, linewidth=0.8, alpha=0.8)

        # Body rectangle
        rect_bottom = min(o, c)
        ax1.add_patch(plt.Rectangle(
            (date_nums[i] - body_width / 2, rect_bottom),
            body_width, max(body_h, 0.01),
            facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9
        ))

    # MAs
    ax1.plot(date_nums, ma5, color="#ffd700", linewidth=0.8, alpha=0.7, label="MA5")
    ax1.plot(date_nums, ma10, color="#ff69b4", linewidth=0.8, alpha=0.7, label="MA10")
    ax1.plot(date_nums, ma20, color="#00bfff", linewidth=1.0, alpha=0.7, label="MA20")

    # ── Event annotations (text labels on chart) ──────────────────
    event_colors = {
        "JOC": "#00ff7f", "SOS": "#00ff00", "LPS": "#90ee90",
        "Spring": "#00bfff",
        "UT": "#ff4500", "SOW": "#ff0000", "BC": "#ff8c00",
    }
    label_offset = np.nanmean(high - low) * 0.3 if len(high) > 0 else 0.5

    for evt in events:
        evt_date = evt["date"]
        if evt_date not in dates:
            continue
        pos = dates.get_loc(evt_date)
        x = date_nums[pos] if isinstance(pos, int) else date_nums[pos][0]
        y = high[pos] if isinstance(pos, int) else high[pos][0]

        ec = event_colors.get(evt["event"], "#ffffff")

        # Arrow pointing to the candle
        ax1.annotate(
            evt["label"], xy=(x, y), xytext=(x, y + label_offset * 2.5),
            fontsize=7, fontweight="bold", color=ec,
            ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=BG, edgecolor=ec,
                      alpha=0.85, linewidth=1.0),
            arrowprops=dict(arrowstyle="->", color=ec, lw=0.8,
                            connectionstyle="arc3,rad=0.1"),
        )

    # ── Panel 1 styling ──────────────────────────────────────────
    title = f"{name}({code})" if name else code
    ax1.set_title(f"{title} — 威科夫结构分析 (Wyckoff Analysis)",
                  fontsize=13, fontweight="bold", color=TEXT, pad=12)
    ax1.set_ylabel("价格", fontsize=9, color=TEXT)
    ax1.legend(loc="upper left", fontsize=7, facecolor=BG, edgecolor=GRID,
               labelcolor=TEXT)
    ax1.tick_params(colors=TEXT, labelsize=8)
    ax1.grid(True, alpha=0.15, color=GRID)
    for spine in ax1.spines.values():
        spine.set_color(GRID)

    # ── Panel 2: Volume ──────────────────────────────────────────
    for i in range(len(df)):
        color = UP_COLOR if close[i] >= open_[i] else DOWN_COLOR
        ax2.bar(date_nums[i], volume[i], width=body_width,
                color=color, alpha=0.6, edgecolor=color, linewidth=0.3)

    # Volume MA
    vol_ma5_arr = np.concatenate([np.full(4, np.nan), np.convolve(volume, np.ones(5) / 5, mode="valid")])
    ax2.plot(date_nums, vol_ma5_arr, color="#ffd700", linewidth=0.8, alpha=0.5, label="VOL MA5")

    # Mark high-volume bars (potential BC/UT/SOW)
    vol_threshold = np.nanmean(volume) * 2
    for i in range(len(df)):
        if volume[i] > vol_threshold:
            ax2.annotate("!", (date_nums[i], volume[i]),
                         fontsize=6, color="#ff4444", ha="center", va="bottom", fontweight="bold")

    ax2.set_ylabel("成交量", fontsize=9, color=TEXT)
    ax2.tick_params(colors=TEXT, labelsize=8)
    ax2.grid(True, alpha=0.15, color=GRID)
    for spine in ax2.spines.values():
        spine.set_color(GRID)
    ax2.legend(loc="upper left", fontsize=7, facecolor=BG, edgecolor=GRID,
               labelcolor=TEXT)

    # ── X-axis date formatting ───────────────────────────────────
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)
    plt.setp(ax1.xaxis.get_majorticklabels(), visible=False)

    # ── Footer ───────────────────────────────────────────────────
    fig.text(0.5, 0.01,
             f"AI Trading OS · Wyckoff Analysis · {datetime.date.today().isoformat()}  |  "
             f"红涨绿跌 · 事件直接标注于K线上方",
             ha="center", fontsize=7, color="#666666")

    # ── Event legend ─────────────────────────────────────────────
    legend_text = "  ".join([
        "🟢 SOS/JOC/LPS: 看涨信号",
        "🔵 Spring: 黄金买点",
        "🟠 BC: 买入高潮",
        "🔴 UT/SOW: 看跌信号",
    ])
    fig.text(0.5, 0.03, legend_text, ha="center", fontsize=7, color="#888888")

    plt.tight_layout(rect=[0, 0.06, 1, 1])

    # ── Save ─────────────────────────────────────────────────────
    filename = CHART_DIR / f"{code}_{datetime.date.today().isoformat()}_日K.png"
    fig.savefig(filename, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)

    return str(filename)


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="威科夫 K线图生成工具")
    parser.add_argument("--code", required=True, help="股票代码, 如 002636")
    parser.add_argument("--name", default="", help="股票名称")
    parser.add_argument("--days", type=int, default=120, help="K线天数 (默认120)")
    parser.add_argument("--period", default="daily", choices=["daily", "weekly"], help="周期")
    parser.add_argument("--no-detect", action="store_true", help="跳过事件检测")
    args = parser.parse_args()

    print(f"┌─────────────────────────────────────┐")
    print(f"│  威科夫 K线图生成工具               │")
    print(f"│  {args.code} {'(' + args.name + ')' if args.name else ''}")
    print(f"└─────────────────────────────────────┘")

    # 1. Fetch data
    print(f"\n[1/3] 获取K线数据... ", end="", flush=True)
    df = fetch_kline(args.code, args.days, args.period)
    print(f"{len(df)} 条 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    # 2. Detect events
    events = []
    if not args.no_detect:
        print(f"[2/3] 检测威科夫事件... ", end="", flush=True)
        events = detect_wyckoff_events(df)
        print(f"{len(events)} 个事件")
        for e in events:
            print(f"       {e['date'].strftime('%m/%d')}  {e['event']}")

    # 3. Render
    print(f"[3/3] 渲染图表... ", end="", flush=True)
    filepath = render_chart(df, events, args.code, args.name or args.code)
    print(f"\n       → {filepath}")
    print(f"\n✓ 完成! 打开: {filepath}")


if __name__ == "__main__":
    main()
