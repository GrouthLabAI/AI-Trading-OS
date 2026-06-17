# AI Trading OS - Backtest Engine
"""
Wrapper around backtesting.py for strategy validation.

Usage:
    from strategies.backtest_engine import BacktestEngine
    engine = BacktestEngine()
    result = engine.run("002636", strategy_cls, cash=100000, start="2025-01-01")
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional, Type

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

import akshare as ak
from backend.config import PROJECT_ROOT

CHARTS_DIR = PROJECT_ROOT / "charts"
CHARTS_DIR.mkdir(exist_ok=True)


class BacktestEngine:
    """Runs backtests and generates reports."""

    # ── Data loading ──────────────────────────────────────────────

    @staticmethod
    def load_data(code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch OHLCV data for backtesting (Sina source, reliable)."""
        sym = f"sh{code}" if code.startswith(("60", "68")) else f"sz{code}"
        df = ak.stock_zh_a_daily(symbol=sym, adjust="qfq")

        df = df.rename(columns={
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        })

        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()

        # Filter date range
        df = df.loc[start_date:end_date]

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df.dropna()

    # ── Run backtest ──────────────────────────────────────────────

    @staticmethod
    def run(
        code: str,
        strategy_cls: Type[Strategy],
        cash: float = 100000,
        start_date: str = "2024-01-01",
        end_date: str = "",
        **params,
    ) -> dict:
        """Run backtest and return stats dict."""
        if not end_date:
            end_date = datetime.date.today().isoformat()

        df = BacktestEngine.load_data(code, start_date, end_date)
        if len(df) < 30:
            return {"error": f"数据不足: {len(df)} 条 (最少30条)"}

        commission = 0.0003  # 万三佣金
        bt = Backtest(df, strategy_cls, cash=cash, commission=commission, finalize_trades=True)
        stats = bt.run(**params)

        return BacktestEngine._format_stats(code, stats, bt, start_date, end_date)

    # ── Optimize ──────────────────────────────────────────────────

    @staticmethod
    def optimize(
        code: str,
        strategy_cls: Type[Strategy],
        cash: float = 100000,
        start_date: str = "2024-01-01",
        end_date: str = "",
        param_ranges: dict = None,
    ) -> dict:
        """Run parameter optimization via grid search."""
        if not end_date:
            end_date = datetime.date.today().isoformat()

        if not param_ranges:
            return {"error": "请提供参数优化范围"}

        df = BacktestEngine.load_data(code, start_date, end_date)
        if len(df) < 30:
            return {"error": f"数据不足: {len(df)} 条"}

        bt = Backtest(df, strategy_cls, cash=cash, commission=0.0003)

        # Convert param ranges to proper format for optimize()
        # Grid search: each key → list of values to try
        optimize_kwargs = {}
        for key, values in param_ranges.items():
            if isinstance(values, list) and len(values) > 0:
                if isinstance(values[0], float) or all(isinstance(v, float) for v in values):
                    optimize_kwargs[key] = [float(v) for v in values]
                else:
                    optimize_kwargs[key] = [int(v) for v in values]

        try:
            opt_result, heatmap = bt.optimize(
                maximize="Return [%]",
                return_heatmap=True,
                **optimize_kwargs,
            )

            # Run best params
            best_params = {k: v for k, v in opt_result.items()
                          if k in param_ranges and not k.startswith("_")}
            best_stats = BacktestEngine.run(
                code, strategy_cls, cash, start_date, end_date, **best_params
            )

            return {
                "best_params": best_params,
                "best_stats": best_stats,
                "heatmap": _serialize_heatmap(heatmap, param_ranges),
            }
        except Exception as e:
            return {"error": f"优化失败: {str(e)}"}

    # ── 同花顺 style Bokeh chart (interactive) ─────────────────────

    @staticmethod
    def generate_thsc_chart(
        code: str, strategy_name: str,
        strategy_cls: Type[Strategy],
        cash: float = 100000,
        start_date: str = "2024-01-01",
        end_date: str = "",
        **params,
    ) -> str:
        """Generate 同花顺-style interactive K-line chart with Bokeh. Returns HTML string."""
        from bokeh.plotting import figure
        from bokeh.models import (ColumnDataSource, CustomJS, HoverTool, Span,
                                   Band, Range1d, Label, NumeralTickFormatter)
        from bokeh.layouts import gridplot, column
        from bokeh.resources import CDN
        from bokeh.embed import components

        if not end_date:
            end_date = datetime.date.today().isoformat()

        df = BacktestEngine.load_data(code, start_date, end_date)
        bt = Backtest(df, strategy_cls, cash=cash, commission=0.0003)
        stats = bt.run(**params)

        # ── 同花顺 light theme colors ──
        BG      = "#ffffff"
        GRID    = "#ebebeb"
        AXIS_C  = "#999999"
        RED_UP  = "#e8172b"   # 涨 - 红色实心
        GREEN_DN= "#0dab25"   # 跌 - 绿色实心
        DOJI_C  = "#333333"   # 十字星
        MA_COLORS = {"MA5": "#f2a603", "MA10": "#d44de8", "MA20": "#2b7ee8", "MA60": "#e84e2b"}
        VOL_RED = "#e8172b"; VOL_GREEN = "#0dab25"
        BUY_C   = "#ff6600"; SELL_C = "#00cc66"

        dates  = df.index
        close  = df["Close"].values.astype(float)
        open_  = df["Open"].values.astype(float)
        high   = df["High"].values.astype(float)
        low    = df["Low"].values.astype(float)
        vol    = df["Volume"].values.astype(float)
        n      = len(dates)

        def _ma(arr, k):
            out = np.full(len(arr), np.nan)
            for i in range(k - 1, len(arr)):
                out[i] = arr[i - k + 1:i + 1].mean()
            return out

        ma5 = _ma(close, 5); ma10 = _ma(close, 10)
        ma20 = _ma(close, 20); ma60 = _ma(close, 60)
        vma5 = _ma(vol, 5)

        # Datetime to milliseconds for Bokeh datetime axis
        DAY_MS = 86_400_000
        x_ms   = np.array([pd.Timestamp(d).value // 10**6 for d in dates], dtype=float)
        bar_w  = 0.6 * DAY_MS  # candle body width

        inc  = close >= open_
        body_top    = np.where(inc, close, open_)
        body_bottom = np.where(inc, open_, close)
        body_h      = np.maximum(body_top - body_bottom, 1e-6)
        colors_body = [RED_UP if inc[i] else GREEN_DN for i in range(n)]
        colors_wick = colors_body[:]
        vol_colors  = [VOL_RED if inc[i] else VOL_GREEN for i in range(n)]

        def _clean(arr):
            return [None if np.isnan(v) else float(v) for v in arr]

        # Equity curve from _equity_curve
        eq_dates, eq_vals = [], []
        if "_equity_curve" in stats and stats["_equity_curve"] is not None:
            eqdf = stats["_equity_curve"]
            step = max(1, len(eqdf) // 500)
            for i in range(0, len(eqdf), step):
                ev = float(eqdf["Equity"].iloc[i])
                if np.isfinite(ev):
                    eq_dates.append(pd.Timestamp(eqdf.index[i]).value // 10**6)
                    eq_vals.append(ev)

        # Drawdown series
        dd_dates, dd_vals = [], []
        if "_equity_curve" in stats and stats["_equity_curve"] is not None:
            eqdf = stats["_equity_curve"]
            if "DrawdownPct" in eqdf.columns:
                step = max(1, len(eqdf) // 500)
                for i in range(0, len(eqdf), step):
                    dv = float(eqdf["DrawdownPct"].iloc[i])
                    if np.isfinite(dv):
                        dd_dates.append(pd.Timestamp(eqdf.index[i]).value // 10**6)
                        dd_vals.append(dv * -100)

        ksrc = ColumnDataSource(data=dict(
            x=x_ms.tolist(), date_str=[str(d)[:10] for d in dates],
            open=open_.tolist(), high=high.tolist(), low=low.tolist(), close=close.tolist(),
            vol=vol.tolist(),
            bar_w=[bar_w] * n,
            body_top=body_top.tolist(), body_bottom=body_bottom.tolist(), body_h=body_h.tolist(),
            colors_body=colors_body, colors_wick=colors_wick, vol_colors=vol_colors,
            ma5=_clean(ma5), ma10=_clean(ma10), ma20=_clean(ma20), ma60=_clean(ma60),
            vma5=_clean(vma5),
        ))

        # Trade markers — buy below candle low, sell above candle high
        bx, by_marker, by_label, btip = [], [], [], []
        sx, sy_marker, sy_label, stip = [], [], [], []
        if "_trades" in stats and stats["_trades"] is not None:
            for _, t in stats["_trades"].iterrows():
                et = t.get("EntryTime"); xt = t.get("ExitTime")
                ep = float(t.get("EntryPrice", 0) or 0)
                xp = float(t.get("ExitPrice", 0) or 0)
                pnl = float(t.get("PnL", 0) or 0)
                rpct = float(t.get("ReturnPct", 0) or 0) * 100
                if pd.notna(et) and ep > 0:
                    ex_ms = pd.Timestamp(et).value // 10**6
                    # Find the low of the entry bar for marker placement
                    idx_arr = np.where(x_ms == ex_ms)[0]
                    bar_low = float(low[idx_arr[0]]) if len(idx_arr) > 0 else ep
                    offset = bar_low * 0.015
                    bx.append(ex_ms)
                    by_marker.append(bar_low - offset)
                    by_label.append(bar_low - offset * 3.5)
                    btip.append(f"买入 ¥{ep:.2f}")
                if pd.notna(xt) and xp > 0:
                    ex_ms = pd.Timestamp(xt).value // 10**6
                    idx_arr = np.where(x_ms == ex_ms)[0]
                    bar_high = float(high[idx_arr[0]]) if len(idx_arr) > 0 else xp
                    offset = bar_high * 0.015
                    sx.append(ex_ms)
                    sy_marker.append(bar_high + offset)
                    sy_label.append(bar_high + offset * 3.5)
                    stip.append(f"卖出 ¥{xp:.2f}  盈亏 ¥{pnl:+.0f}  ({rpct:+.1f}%)")

        buy_src  = ColumnDataSource(data=dict(x=bx, y=by_marker, label_y=by_label, tip=btip))
        sell_src = ColumnDataSource(data=dict(x=sx, y=sy_marker, label_y=sy_label, tip=stip))

        # ── Shared x range (so all panels scroll together) ──
        toolbar_opts = dict(toolbar_location="above",
                            tools="xpan,xwheel_zoom,box_zoom,reset,save",
                            active_scroll="xwheel_zoom")
        shared_x = None  # will be set from p1

        def _style(p, bottom_axis=True):
            p.background_fill_color = BG
            p.border_fill_color = BG
            p.grid.grid_line_color = GRID
            p.grid.grid_line_alpha = 0.8
            p.axis.axis_label_text_color = AXIS_C
            p.axis.major_label_text_color = AXIS_C
            p.axis.major_tick_line_color = GRID
            p.axis.minor_tick_line_color = None
            p.outline_line_color = GRID
            if not bottom_axis:
                p.xaxis.major_label_text_font_size = "0pt"

        # ── Panel 1: K线 + MA ──
        title_str = f"{code}  {strategy_name}  {start_date} ~ {end_date}"
        p1 = figure(width=1100, height=480, x_axis_type="datetime",
                    title=title_str, **toolbar_opts)
        shared_x = p1.x_range
        _style(p1, bottom_axis=False)
        p1.title.text_color = "#333"
        p1.title.text_font_size = "12px"
        p1.title.text_font_style = "normal"

        # Wicks (high-low line)
        p1.segment(x0="x", y0="low", x1="x", y1="high",
                   source=ksrc, color="colors_wick", line_width=1.0)
        # Candle bodies
        p1.vbar(x="x", width="bar_w", top="body_top", bottom="body_bottom",
                source=ksrc, fill_color="colors_body",
                line_color="colors_body", line_width=0.5, alpha=0.95)

        # MA lines
        for ma_name, ma_color in MA_COLORS.items():
            col_key = ma_name.lower()
            p1.line(x="x", y=col_key, source=ksrc,
                    color=ma_color, line_width=1.2, alpha=0.85,
                    legend_label=ma_name, name=ma_name)

        # Buy markers (upward triangle below bar)
        buy_r = p1.scatter(x="x", y="y", source=buy_src,
                           marker="triangle", size=12, color=BUY_C,
                           line_color="#cc4400", line_width=0.8,
                           alpha=0.95, legend_label="买入")
        sell_r = p1.scatter(x="x", y="y", source=sell_src,
                            marker="inverted_triangle", size=12, color=SELL_C,
                            line_color="#009944", line_width=0.8,
                            alpha=0.95, legend_label="卖出")

        # Invisible wide bar for candle hover
        hover_bar = p1.vbar(x="x", width="bar_w", top="high", bottom="low",
                            source=ksrc, fill_alpha=0, line_alpha=0)

        p1.add_tools(HoverTool(
            renderers=[hover_bar],
            tooltips=[
                ("日期", "@date_str"),
                ("开", "@open{0.00}"),
                ("高", "@high{0.00}"),
                ("低", "@low{0.00}"),
                ("收", "@close{0.00}"),
                ("量", "@vol{0,0}"),
            ],
            mode="vline",
        ))
        p1.add_tools(HoverTool(
            renderers=[buy_r, sell_r],
            tooltips=[("", "@tip")],
            mode="mouse",
        ))

        p1.legend.click_policy = "hide"
        p1.legend.location = "top_left"
        p1.legend.background_fill_color = BG
        p1.legend.background_fill_alpha = 0.85
        p1.legend.border_line_color = GRID
        p1.legend.label_text_font_size = "10px"
        p1.legend.spacing = 2
        p1.legend.padding = 4

        # ── Panel 2: Volume ──
        p2 = figure(width=1100, height=130, x_axis_type="datetime",
                    x_range=shared_x, toolbar_location=None)
        _style(p2, bottom_axis=False)
        p2.vbar(x="x", width="bar_w", top="vol", bottom=0,
                source=ksrc, fill_color="vol_colors",
                line_color="vol_colors", line_width=0.3, alpha=0.85)
        p2.line(x="x", y="vma5", source=ksrc,
                color="#f2a603", line_width=1.0, alpha=0.8, legend_label="VOL MA5")
        p2.legend.location = "top_left"
        p2.legend.background_fill_color = BG
        p2.legend.label_text_font_size = "9px"
        p2.legend.padding = 3
        p2.yaxis.formatter = NumeralTickFormatter(format="0.0a")
        p2.add_tools(HoverTool(
            tooltips=[("日期", "@date_str"), ("成交量", "@vol{0,0}")],
            mode="vline",
        ))

        # ── Panel 3: Equity curve ──
        p3 = figure(width=1100, height=130, x_axis_type="datetime",
                    x_range=shared_x, toolbar_location=None)
        _style(p3, bottom_axis=False)
        if eq_dates:
            eq_src = ColumnDataSource(data=dict(x=eq_dates, eq=eq_vals))
            p3.line(x="x", y="eq", source=eq_src,
                    color="#2b7ee8", line_width=1.5, legend_label="权益曲线")
            # Fill under curve
            from bokeh.models import Band
            p3.varea(x="x", y1=min(eq_vals), y2="eq", source=eq_src,
                     fill_color="#2b7ee8", fill_alpha=0.12)
        p3.legend.location = "top_left"
        p3.legend.background_fill_color = BG
        p3.legend.label_text_font_size = "9px"
        p3.legend.padding = 3
        p3.yaxis.formatter = NumeralTickFormatter(format="0,0")

        # ── Panel 4: Drawdown ──
        p4 = figure(width=1100, height=110, x_axis_type="datetime",
                    x_range=shared_x, toolbar_location=None)
        _style(p4, bottom_axis=True)
        if dd_dates:
            dd_src = ColumnDataSource(data=dict(x=dd_dates, dd=dd_vals))
            p4.varea(x="x", y1="dd", y2=0, source=dd_src,
                     fill_color="#e8172b", fill_alpha=0.35)
            p4.line(x="x", y="dd", source=dd_src,
                    color="#e8172b", line_width=1.0, alpha=0.7, legend_label="回撤%")
        p4.legend.location = "bottom_left"
        p4.legend.background_fill_color = BG
        p4.legend.label_text_font_size = "9px"
        p4.legend.padding = 3

        # ── Synchronized crosshair (十字光标线) ──
        # Uses Span + CustomJS so the vertical line贯穿联动 all 4 panels
        XHAIR_COLOR = "#333"
        XHAIR_ALPHA = 0.5
        XHAIR_WIDTH = 1

        vspan1 = Span(dimension="height", line_color=XHAIR_COLOR,
                      line_dash="dashed", line_alpha=XHAIR_ALPHA, line_width=XHAIR_WIDTH)
        vspan2 = Span(dimension="height", line_color=XHAIR_COLOR,
                      line_dash="dashed", line_alpha=XHAIR_ALPHA, line_width=XHAIR_WIDTH)
        vspan3 = Span(dimension="height", line_color=XHAIR_COLOR,
                      line_dash="dashed", line_alpha=XHAIR_ALPHA, line_width=XHAIR_WIDTH)
        vspan4 = Span(dimension="height", line_color=XHAIR_COLOR,
                      line_dash="dashed", line_alpha=XHAIR_ALPHA, line_width=XHAIR_WIDTH)
        hspan1 = Span(dimension="width", line_color=XHAIR_COLOR,
                      line_dash="dashed", line_alpha=XHAIR_ALPHA, line_width=XHAIR_WIDTH)

        p1.add_layout(vspan1)
        p1.add_layout(hspan1)
        p2.add_layout(vspan2)
        p3.add_layout(vspan3)
        p4.add_layout(vspan4)

        crosshair_cb_p1 = CustomJS(args=dict(
            vs1=vspan1, vs2=vspan2, vs3=vspan3, vs4=vspan4, hs=hspan1
        ), code="""
            const x = cb_data.geometry.x;
            const y = cb_data.geometry.y;
            if (x !== undefined) {
                vs1.location = x;
                vs2.location = x;
                vs3.location = x;
                vs4.location = x;
            }
            if (y !== undefined) {
                hs.location = y;
            }
        """)
        crosshair_cb_v = CustomJS(args=dict(
            vs1=vspan1, vs2=vspan2, vs3=vspan3, vs4=vspan4
        ), code="""
            const x = cb_data.geometry.x;
            if (x !== undefined) {
                vs1.location = x;
                vs2.location = x;
                vs3.location = x;
                vs4.location = x;
            }
        """)

        # Sync hover tools on each panel (no tooltips — only drives crosshair)
        p1.add_tools(HoverTool(mode="mouse", callback=crosshair_cb_p1))
        p2.add_tools(HoverTool(mode="vline", callback=crosshair_cb_v))
        p3.add_tools(HoverTool(mode="vline", callback=crosshair_cb_v))
        p4.add_tools(HoverTool(mode="vline", callback=crosshair_cb_v))

        # ── Stats bar values (sanitize NaN/Inf from backtesting.py) ──
        def _sf(v, default=0.0):
            try:
                fv = float(v)
                if not np.isfinite(fv):
                    return default
                return fv
            except (ValueError, TypeError):
                return default

        ret  = _sf(stats.get("Return [%]", 0))
        bhr  = _sf(stats.get("Buy & Hold Return [%]", 0))
        wr   = _sf(stats.get("Win Rate [%]", 0))
        dd_v = _sf(stats.get("Max. Drawdown [%]", 0))
        sr   = _sf(stats.get("Sharpe Ratio", 0))
        nt   = int(_sf(stats.get("# Trades", 0)))
        ret_color  = "#e8172b" if ret >= 0 else "#0dab25"
        bhr_color  = "#e8172b" if bhr >= 0 else "#0dab25"

        # ── Combine into gridplot ──
        gp = gridplot(
            [[p1], [p2], [p3], [p4]],
            sizing_mode="stretch_width",
            merge_tools=False,
        )

        script, div = components(gp)
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{CDN.render()}
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f5f5;color:#333}}
.thsc-wrap{{background:#fff;border:1px solid #ddd;border-radius:4px;overflow:hidden}}
.thsc-header{{background:#fff;border-bottom:1px solid #eee;padding:6px 12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.thsc-code{{font-size:17px;font-weight:700;color:#222;letter-spacing:0.5px}}
.thsc-name{{font-size:12px;color:#888;padding-left:4px}}
.thsc-stats{{display:flex;gap:18px;margin-left:auto;flex-wrap:wrap}}
.stat-item{{display:flex;flex-direction:column;align-items:center;min-width:60px}}
.stat-label{{font-size:10px;color:#aaa;margin-bottom:1px}}
.stat-value{{font-size:13px;font-weight:600}}
.up{{color:#e8172b}}.dn{{color:#0dab25}}.neu{{color:#555}}
.thsc-legend{{background:#fafafa;border-bottom:1px solid #eee;padding:4px 12px;font-size:11px;color:#777;display:flex;gap:16px;flex-wrap:wrap}}
.leg-dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:3px;vertical-align:middle}}
.bk-root .bk-toolbar{{background:transparent!important}}
</style>
</head>
<body>
<div class="thsc-wrap">
  <div class="thsc-header">
    <span class="thsc-code">{code}</span>
    <span class="thsc-name">{strategy_name}</span>
    <div class="thsc-stats">
      <div class="stat-item"><span class="stat-label">策略收益</span><span class="stat-value {'up' if ret>=0 else 'dn'}">{ret:+.2f}%</span></div>
      <div class="stat-item"><span class="stat-label">买入持有</span><span class="stat-value {'up' if bhr>=0 else 'dn'}">{bhr:+.2f}%</span></div>
      <div class="stat-item"><span class="stat-label">最大回撤</span><span class="stat-value dn">{dd_v:.2f}%</span></div>
      <div class="stat-item"><span class="stat-label">夏普比率</span><span class="stat-value {'up' if sr>=1 else 'neu'}">{sr:.2f}</span></div>
      <div class="stat-item"><span class="stat-label">胜率</span><span class="stat-value {'up' if wr>=50 else 'dn'}">{wr:.0f}%</span></div>
      <div class="stat-item"><span class="stat-label">交易次数</span><span class="stat-value neu">{nt}笔</span></div>
    </div>
  </div>
  <div class="thsc-legend">
    <span><span class="leg-dot" style="background:#f2a603"></span>MA5</span>
    <span><span class="leg-dot" style="background:#d44de8"></span>MA10</span>
    <span><span class="leg-dot" style="background:#2b7ee8"></span>MA20</span>
    <span><span class="leg-dot" style="background:#e84e2b"></span>MA60</span>
    <span><span class="leg-dot" style="background:#ff6600"></span>买入信号</span>
    <span><span class="leg-dot" style="background:#00cc66"></span>卖出信号</span>
  </div>
  {div}
</div>
{script}
</body>
</html>"""


    # ── Generate HTML report ──────────────────────────────────────────
    @staticmethod
    def generate_html(
        code: str, strategy_name: str,
        strategy_cls: Type[Strategy],
        cash: float = 100000,
        start_date: str = "2024-01-01",
        end_date: str = "",
        **params,
    ) -> str:
        """Generate standalone Bokeh HTML report."""
        return BacktestEngine.generate_thsc_chart(
            code, strategy_name, strategy_cls, cash, start_date, end_date, **params)

    # ── Format stats to JSON ──────────────────────────────────────────
    @staticmethod
    def _format_stats(code: str, stats: pd.Series, bt: Backtest,
                      start: str, end: str) -> dict:
        """Convert backtesting.py stats to JSON-friendly dict."""
        trades_list = []
        if "_trades" in stats and stats["_trades"] is not None:
            for _, t in stats["_trades"].iterrows():
                entry_time = t.get("EntryTime", None); exit_time = t.get("ExitTime", None)
                entry_ts = str(entry_time)[:19] if pd.notna(entry_time) else ""
                exit_ts = str(exit_time)[:19] if pd.notna(exit_time) else ""
                hold_days = 0
                if pd.notna(entry_time) and pd.notna(exit_time):
                    try: hold_days = (pd.Timestamp(exit_time)-pd.Timestamp(entry_time)).days
                    except: pass
                trades_list.append({
                    "entry_time": entry_ts, "exit_time": exit_ts,
                    "entry_price": round(float(t.get("EntryPrice",0) or 0),2),
                    "exit_price": round(float(t.get("ExitPrice",0) or 0),2),
                    "size": int(t.get("Size",0) or 0),
                    "pnl": round(float(t.get("PnL",0) or 0),2),
                    "return_pct": round(float(t.get("ReturnPct",0) or 0),4),
                    "hold_days": hold_days,
                })

        equity_curve = []
        if "_equity_curve" in stats and stats["_equity_curve"] is not None:
            eq = stats["_equity_curve"]
            step = max(1, len(eq)//200)
            for i in range(0, len(eq), step):
                try:
                    equity_curve.append({"date": str(eq.index[i])[:10], "equity": round(float(eq["Equity"].iloc[i]),2)})
                except: pass

        def _f(key: str, default=0.0) -> float:
            try:
                val = float(stats.get(key, default))
                if not np.isfinite(val):
                    return default
                return round(val, 2)
            except:
                return default

        return {
            "code": code, "date_range": f"{start} ~ {end}",
            "stats": {
                "start_value": _f("Start"), "end_value": _f("End"),
                "return_pct": _f("Return [%]"), "buy_hold_return_pct": _f("Buy & Hold Return [%]"),
                "max_drawdown_pct": _f("Max. Drawdown [%]"), "avg_drawdown_pct": _f("Avg. Drawdown [%]"),
                "sharpe_ratio": _f("Sharpe Ratio"), "sortino_ratio": _f("Sortino Ratio"),
                "win_rate_pct": _f("Win Rate [%]"), "best_trade_pct": _f("Best Trade [%]"),
                "worst_trade_pct": _f("Worst Trade [%]"), "avg_trade_pct": _f("Avg. Trade [%]"),
                "total_trades": int(stats.get("# Trades",0)),
            },
            "trades": trades_list, "equity_curve": equity_curve,
            "risk_metrics": _compute_risk_metrics(stats, trades_list),
        }


# ── Module-level helpers ────────────────────────────────────────────

def _sanitize_float(val: float, default: float = 0.0) -> float:
    """Replace NaN/Inf with a JSON-safe default."""
    if val is None:
        return default
    try:
        if not np.isfinite(float(val)):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _compute_risk_metrics(stats: pd.Series, trades: list[dict]) -> dict:
    """Compute extended risk metrics from backtest results."""
    import numpy as np

    pnls = [t["pnl"] for t in trades] if trades else []
    returns = [t["return_pct"] for t in trades] if trades else []

    # Winners & losers
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    avg_win = _sanitize_float(np.mean(winners)) if winners else 0.0
    avg_loss = _sanitize_float(np.mean(losers)) if losers else 0.0
    profit_factor = abs(sum(winners) / max(abs(sum(losers)), 0.01)) if winners and losers else 0.0

    # Consecutive streaks
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    current_wins = 0
    current_losses = 0
    for p in pnls:
        if p > 0:
            current_wins += 1; current_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, current_wins)
        else:
            current_losses += 1; current_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, current_losses)

    # Calmar: annualized return / max drawdown
    return_pct = _sanitize_float(float(stats.get("Return [%]", 0)))
    max_dd = abs(_sanitize_float(float(stats.get("Max. Drawdown [%]", 1)), 1.0))
    calmar = return_pct / max_dd if max_dd > 0.001 else 0.0
    calmar = _sanitize_float(calmar)

    # Annualized volatility (from trades)
    if len(returns) > 1:
        ann_vol = _sanitize_float(np.std(returns)) * np.sqrt(252) * 100
    else:
        ann_vol = 0.0

    # Value at Risk (95%, 99%)
    if len(returns) > 5:
        var_95 = _sanitize_float(np.percentile(returns, 5)) * 100
        var_99 = _sanitize_float(np.percentile(returns, 1)) * 100
    else:
        var_95 = var_99 = 0.0

    # Expectancy
    win_rate = _sanitize_float(float(stats.get("Win Rate [%]", 0))) / 100.0
    expectancy = (win_rate * avg_win + (1 - win_rate) * avg_loss) if winners or losers else 0.0
    expectancy = _sanitize_float(expectancy)

    def _r(v: float) -> float:
        """Round after sanitizing."""
        return round(_sanitize_float(v), 2)

    return {
        "avg_win": _r(avg_win),
        "avg_loss": _r(avg_loss),
        "profit_loss_ratio": _r(abs(avg_win / max(abs(avg_loss), 0.01))),
        "profit_factor": _r(profit_factor),
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
        "calmar_ratio": _r(calmar),
        "annual_volatility_pct": _r(ann_vol),
        "var_95_pct": _r(var_95),
        "var_99_pct": _r(var_99),
        "expectancy": _r(expectancy),
    }


# ── Helper ─────────────────────────────────────────────────────────

def _serialize_heatmap(heatmap, param_ranges: dict) -> dict:
    """Convert heatmap DataFrame to JSON-friendly dict."""
    if heatmap is None or heatmap.empty:
        return {}

    try:
        # heatmap is a multi-index Series from backtesting.py optimize
        if isinstance(heatmap, pd.Series):
            result = {}
            for idx, val in heatmap.items():
                key = "_".join(str(i) for i in (idx if isinstance(idx, tuple) else [idx]))
                result[key] = round(float(val), 2)
            return result

        return {"data": heatmap.to_dict()}
    except Exception:
        return {}
