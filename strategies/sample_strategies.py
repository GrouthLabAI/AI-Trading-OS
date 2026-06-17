# AI Trading OS - Sample Backtesting Strategies
"""
Pre-built strategies for backtesting.py engine.

Each strategy class attribute is an optimizable parameter:
  - Defined as class-level variable (backtesting.py convention)
  - Exposed to frontend form for param optimization
  - Grid search via Backtest.optimize(**param_ranges)

Usage:
    from strategies.sample_strategies import FirstBoardStrategy
    bt = Backtest(df, FirstBoardStrategy, cash=100000)
    stats = bt.run()
"""

from backtesting import Strategy
from backtesting.lib import crossover
import numpy as np
import pandas as pd


# ── A-share specific helpers ─────────────────────────────────────

def _is_limit_up(open_, high, low, close):
    """Check if a day was a limit-up (10% or 20% for 创业板/科创板)."""
    if open_ <= 0: return False
    chg = (close - open_) / open_
    return chg >= 0.095

def _is_limit_down(open_, high, low, close):
    if open_ <= 0: return False
    chg = (close - open_) / open_
    return chg <= -0.095

def _can_buy(open_, high, low, close):
    """A股限制: 涨停封死买不到，跌停卖不出"""
    return not _is_limit_up(open_, high, low, close)

def _can_sell(open_, high, low, close):
    return not _is_limit_down(open_, high, low, close)


# ═══════════════════════════════════════════════════════════════════
# Strategy 1: 首板战法
# ═══════════════════════════════════════════════════════════════════

class FirstBoardStrategy(Strategy):
    """
    首板战法 — 涨停日次日开盘买入，持有 N 天后卖出。
    A股适配: 涨停日买不到(跳过), T+1(框架默认次日执行)
    """

    hold_days = 3; min_turnover = 2.0; max_turnover = 15.0; stop_loss_pct = -5.0

    def init(self):
        self.limit_up = self.I(
            lambda o, h, l, c: np.array([_is_limit_up(o[i],h[i],l[i],c[i]) for i in range(len(o))]),
            self.data.Open, self.data.High, self.data.Low, self.data.Close,
            name="涨停检测", plot=False,
        )

    def next(self):
        idx = len(self.data) - 1
        if idx < 1: return
        if self.limit_up[idx - 1] and not self.position:
            # A股: 涨停封死买不到，如果今天开盘价就是涨停价则放弃
            if _can_buy(self.data.Open[-1], self.data.High[-1], self.data.Low[-1], self.data.Close[-1]):
                self.buy()
        if self.position:
            hold_bars = idx - self.trades[-1].entry_bar if self.trades else 0
            if self.data.Close[-1] <= self.trades[-1].entry_price * (1 + self.stop_loss_pct / 100):
                if _can_sell(self.data.Open[-1], self.data.High[-1], self.data.Low[-1], self.data.Close[-1]):
                    self.position.close()
            elif hold_bars >= self.hold_days:
                if _can_sell(self.data.Open[-1], self.data.High[-1], self.data.Low[-1], self.data.Close[-1]):
                    self.position.close()


# ═══════════════════════════════════════════════════════════════════
# Strategy 2: 龙头低吸
# ═══════════════════════════════════════════════════════════════════

class DragonLowBuyStrategy(Strategy):
    """
    龙头低吸 — 价格回调到 MA 均线附近时买入，反弹后卖出。

    Logic: close < MA(ma_period) * (1 + pullback_pct/100) → 买入
           close > entry * (1 + take_profit_pct/100) → 卖出
    """

    ma_period = 10          # 均线周期
    pullback_pct = -3.0     # 回调幅度（负数=低于均线）
    take_profit_pct = 8.0   # 止盈百分比
    stop_loss_pct = -5.0    # 止损百分比
    max_hold_days = 10      # 最大持有天数

    def init(self):
        close = self.data.Close
        # Simple moving average
        self.ma = self.I(
            lambda x: pd.Series(x).rolling(self.ma_period).mean().values,
            close, name=f"MA{self.ma_period}", overlay=True,
        )

    def next(self):
        if len(self.data) < self.ma_period + 1:
            return

        close = self.data.Close[-1]
        ma_val = self.ma[-1]

        # Buy signal: price pulls back near MA
        if not self.position and ma_val > 0:
            deviation = (close - ma_val) / ma_val * 100
            if deviation <= self.pullback_pct:
                self.buy()

        # Exit
        if self.position:
            entry = self.trades[-1].entry_price
            bars = len(self.data) - self.trades[-1].entry_bar

            # Stop loss
            if close <= entry * (1 + self.stop_loss_pct / 100):
                self.position.close()
            # Take profit
            elif close >= entry * (1 + self.take_profit_pct / 100):
                self.position.close()
            # Time exit
            elif bars >= self.max_hold_days:
                self.position.close()


# ═══════════════════════════════════════════════════════════════════
# Strategy 3: 放量突破
# ═══════════════════════════════════════════════════════════════════

class BreakoutStrategy(Strategy):
    """
    放量突破 — 成交量放大 + 价格突破 N 日高点 → 买入。

    Logic: volume > ma(volume, vol_period) * vol_ratio
           AND close > highest(high, lookback) → 买入
    """

    lookback = 20           # 突破周期
    vol_period = 5          # 均量周期
    vol_ratio = 1.5         # 量比阈值
    take_profit_pct = 10.0  # 止盈百分比
    stop_loss_pct = -5.0    # 止损百分比
    max_hold_days = 15      # 最大持有天数

    def init(self):
        close = self.data.Close
        volume = self.data.Volume

        self.vol_ma = self.I(
            lambda x: pd.Series(x).rolling(self.vol_period).mean().values,
            volume, name=f"VOL_MA{self.vol_period}", plot=False,
        )
        self.highest_high = self.I(
            lambda x: pd.Series(x).rolling(self.lookback).max().values,
            self.data.High, name=f"HH{self.lookback}", overlay=True,
        )

    def next(self):
        if len(self.data) < self.lookback + 1:
            return

        close = self.data.Close[-1]
        volume = self.data.Volume[-1]
        vol_ma_val = self.vol_ma[-1]

        # Buy signal: volume breakout + price breakout
        if not self.position and vol_ma_val > 0:
            vol_surge = volume > vol_ma_val * self.vol_ratio
            price_break = close >= self.highest_high[-1] * 0.99
            if vol_surge and price_break:
                self.buy()

        # Exit
        if self.position:
            entry = self.trades[-1].entry_price
            bars = len(self.data) - self.trades[-1].entry_bar

            if close <= entry * (1 + self.stop_loss_pct / 100):
                self.position.close()
            elif close >= entry * (1 + self.take_profit_pct / 100):
                self.position.close()
            elif bars >= self.max_hold_days:
                self.position.close()


# ═══════════════════════════════════════════════════════════════════
# Strategy 4: 威科夫 SOS/JOC 突破
# ═══════════════════════════════════════════════════════════════════

class WyckoffSOSStrategy(Strategy):
    """
    威科夫 SOS/JOC — 检测到强势信号或突破后买入。

    SOS: 放量阳线 + 延续上涨 + 供应不足（下影线短）
    JOC: 放量突破20日高点

    信号日次日开盘买入，持有N天后卖出。
    """

    vol_ratio = 1.2        # 量比阈值（>5日均量倍数）
    breakout_pct = 1.5     # 突破幅度%（突破前高的百分比）
    hold_days = 5          # 持有天数
    stop_loss_pct = -5.0   # 止损%
    take_profit_pct = 15.0 # 止盈%

    def init(self):
        close = self.data.Close
        volume = self.data.Volume

        def ma(arr, n):
            s = pd.Series(arr).rolling(n).mean()
            return s.values

        self.vol_ma5 = self.I(ma, volume, 5, name="VOL_MA5", plot=False)

        def highest(arr, n):
            s = pd.Series(arr).rolling(n).max()
            return s.values

        self.hh20 = self.I(highest, self.data.High, 20, name="HH20", overlay=True)

    def next(self):
        idx = len(self.data) - 1
        if idx < 20:
            return

        close = self.data.Close[-1]
        open_ = self.data.Open[-1]
        high = self.data.High[-1]
        low = self.data.Low[-1]
        volume = self.data.Volume[-1]

        body = close - open_
        lower_shadow = min(close, open_) - low

        # SOS condition: volume surge + bullish + small lower shadow (supply exhausted)
        is_sos = (volume > self.vol_ma5[-1] * self.vol_ratio
                  and body > 0
                  and close > self.data.Close[-2]
                  and lower_shadow < abs(body) * 0.3)

        # JOC condition: breakout above 20-day high
        is_joc = (close >= self.hh20[-1] * (1 + self.breakout_pct / 100)
                  and volume > self.vol_ma5[-1] * self.vol_ratio)

        if not self.position and (is_sos or is_joc):
            self.buy()

        if self.position:
            entry = self.trades[-1].entry_price
            bars = idx - self.trades[-1].entry_bar

            if close <= entry * (1 + self.stop_loss_pct / 100):
                self.position.close()
            elif close >= entry * (1 + self.take_profit_pct / 100):
                self.position.close()
            elif bars >= self.hold_days:
                self.position.close()


# ═══════════════════════════════════════════════════════════════════
# Strategy 5: 威科夫 Spring/LPS 低吸
# ═══════════════════════════════════════════════════════════════════

class WyckoffSpringStrategy(Strategy):
    """
    威科夫 Spring/LPS — 回调低吸。

    Spring: 价格跌破支撑 → 缩量 → 迅速收回（弹簧效应）
    LPS: 缩量回调到支撑附近 → 小实体确认 → 买入

    在回调到支撑位且缩量时买入。
    """

    support_lookback = 20  # 支撑计算周期
    spring_pct = -2.0      # Spring跌破支撑的幅度%（负数）
    volume_decay = 0.6     # 缩量阈值（<前期均量比例）
    hold_days = 8          # 持有天数
    stop_loss_pct = -4.0   # 止损%
    take_profit_pct = 20.0 # 止盈%

    def init(self):
        close = self.data.Close
        low = self.data.Low
        volume = self.data.Volume

        def lowest(arr, n):
            s = pd.Series(arr).rolling(n).min()
            return s.values

        def ma(arr, n):
            s = pd.Series(arr).rolling(n).mean()
            return s.values

        self.support = self.I(lowest, low, self.support_lookback, name="Support", overlay=True, color="blue")
        self.vol_ma10 = self.I(ma, volume, 10, name="VOL_MA10", plot=False)

    def next(self):
        idx = len(self.data) - 1
        if idx < self.support_lookback:
            return

        close = self.data.Close[-1]
        open_ = self.data.Open[-1]
        low = self.data.Low[-1]
        volume = self.data.Volume[-1]

        body = close - open_
        spread = self.data.High[-1] - low
        support_val = self.support[-1]

        # Spring condition: dip below support, low volume, recover same day
        is_spring = (support_val > 0
                     and low < support_val * (1 + self.spring_pct / 100)
                     and close > support_val
                     and volume < self.vol_ma10[-1] * self.volume_decay
                     and body > 0)

        # LPS condition: near support, low volume, small body
        is_lps = (support_val > 0
                  and close > support_val
                  and close < support_val * 1.03
                  and volume < self.vol_ma10[-1] * self.volume_decay
                  and abs(body) < spread * 0.35
                  and body > 0)

        if not self.position and (is_spring or is_lps):
            self.buy()

        if self.position:
            entry = self.trades[-1].entry_price
            bars = idx - self.trades[-1].entry_bar

            if close <= entry * (1 + self.stop_loss_pct / 100):
                self.position.close()
            elif close >= entry * (1 + self.take_profit_pct / 100):
                self.position.close()
            elif bars >= self.hold_days:
                self.position.close()


# ── Strategy registry ────────────────────────────────────────────

STRATEGY_REGISTRY = {
    "first_board": {
        "name": "首板战法",
        "class": FirstBoardStrategy,
        "description": "检测涨停日 → 次日开盘买入 → 持有N天卖出",
        "params": {
            "hold_days": {"label": "持有天数", "type": "int", "default": 3, "min": 1, "max": 20},
            "min_turnover": {"label": "最小换手率%", "type": "float", "default": 2.0, "min": 0, "max": 30},
            "max_turnover": {"label": "最大换手率%", "type": "float", "default": 15.0, "min": 5, "max": 50},
            "stop_loss_pct": {"label": "止损%", "type": "float", "default": -5.0, "min": -20, "max": 0},
        },
    },
    "dragon_low": {
        "name": "龙头低吸",
        "class": DragonLowBuyStrategy,
        "description": "回调到均线附近买入 → 反弹止盈",
        "params": {
            "ma_period": {"label": "均线周期", "type": "int", "default": 10, "min": 3, "max": 60},
            "pullback_pct": {"label": "回调幅度%", "type": "float", "default": -3.0, "min": -15, "max": 0},
            "take_profit_pct": {"label": "止盈%", "type": "float", "default": 8.0, "min": 1, "max": 30},
            "stop_loss_pct": {"label": "止损%", "type": "float", "default": -5.0, "min": -20, "max": 0},
            "max_hold_days": {"label": "最大持仓天数", "type": "int", "default": 10, "min": 1, "max": 60},
        },
    },
    "wyckoff_sos": {
        "name": "威科夫 SOS/JOC",
        "class": WyckoffSOSStrategy,
        "description": "检测SOS强势信号/JOC突破 → 次日买入",
        "params": {
            "vol_ratio": {"label": "量比阈值", "type": "float", "default": 1.2, "min": 1.0, "max": 3.0},
            "breakout_pct": {"label": "突破幅度%", "type": "float", "default": 1.5, "min": 0, "max": 10},
            "hold_days": {"label": "持有天数", "type": "int", "default": 5, "min": 1, "max": 30},
            "stop_loss_pct": {"label": "止损%", "type": "float", "default": -5.0, "min": -20, "max": 0},
            "take_profit_pct": {"label": "止盈%", "type": "float", "default": 15.0, "min": 1, "max": 50},
        },
    },
    "wyckoff_spring": {
        "name": "威科夫 Spring/LPS",
        "class": WyckoffSpringStrategy,
        "description": "回调到支撑位缩量 → 低吸买入",
        "params": {
            "support_lookback": {"label": "支撑周期", "type": "int", "default": 20, "min": 5, "max": 60},
            "spring_pct": {"label": "Spring幅度%", "type": "float", "default": -2.0, "min": -10, "max": 0},
            "volume_decay": {"label": "缩量比例", "type": "float", "default": 0.6, "min": 0.2, "max": 1.0},
            "hold_days": {"label": "持有天数", "type": "int", "default": 8, "min": 1, "max": 30},
            "stop_loss_pct": {"label": "止损%", "type": "float", "default": -4.0, "min": -20, "max": 0},
            "take_profit_pct": {"label": "止盈%", "type": "float", "default": 20.0, "min": 1, "max": 50},
        },
    },
    "breakout": {
        "name": "放量突破",
        "class": BreakoutStrategy,
        "description": "成交量放大+突破N日高点 → 买入",
        "params": {
            "lookback": {"label": "突破周期", "type": "int", "default": 20, "min": 5, "max": 120},
            "vol_period": {"label": "均量周期", "type": "int", "default": 5, "min": 2, "max": 30},
            "vol_ratio": {"label": "量比阈值", "type": "float", "default": 1.5, "min": 1.0, "max": 5.0},
            "take_profit_pct": {"label": "止盈%", "type": "float", "default": 10.0, "min": 1, "max": 50},
            "stop_loss_pct": {"label": "止损%", "type": "float", "default": -5.0, "min": -20, "max": 0},
            "max_hold_days": {"label": "最大持仓天数", "type": "int", "default": 15, "min": 1, "max": 120},
        },
    },
}
