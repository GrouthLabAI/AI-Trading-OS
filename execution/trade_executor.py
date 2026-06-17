# AI Trading OS - Trade Executor (Abstract + Factory)
"""
Trade execution abstraction — isolates RPA logic from AI agents.

If the brokerage platform changes, ONLY this layer changes.
Agents are completely unaffected.

Usage:
    from execution.trade_executor import get_executor

    executor = get_executor()              # auto-detects mock vs real
    result = executor.buy("000768", "中航西飞", 23.50, 100)
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from backend.config import settings


@dataclass
class ExecutionResult:
    success: bool
    order_id: str
    code: str
    action: str  # "buy" | "sell"
    price: float
    quantity: int
    message: str
    timestamp: str


# ── Abstract interface ──────────────────────────────────────────────

class BaseTradeExecutor(ABC):
    """All trade executors implement this interface."""

    @abstractmethod
    def buy(self, code: str, name: str, price: float, quantity: int = 100) -> ExecutionResult:
        ...

    @abstractmethod
    def sell(self, code: str, name: str, price: float, quantity: int) -> ExecutionResult:
        ...


# ── Mock executor (for testing) ─────────────────────────────────────

class MockTradeExecutor(BaseTradeExecutor):
    """Simulates trade execution without actual screen automation.

    Logs trades to the database for the full closed-loop experience.
    """

    def buy(self, code: str, name: str, price: float, quantity: int = 100) -> ExecutionResult:
        print(f"[MockExecutor] 模拟买入: {name}({code}) @ {price} x {quantity}")
        return ExecutionResult(
            success=True,
            order_id=f"MOCK-B-{datetime.datetime.now().strftime('%H%M%S')}",
            code=code,
            action="buy",
            price=price,
            quantity=quantity,
            message=f"模拟买入 {name} 成功",
            timestamp=datetime.datetime.now().isoformat(),
        )

    def sell(self, code: str, name: str, price: float, quantity: int) -> ExecutionResult:
        print(f"[MockExecutor] 模拟卖出: {name}({code}) @ {price} x {quantity}")
        return ExecutionResult(
            success=True,
            order_id=f"MOCK-S-{datetime.datetime.now().strftime('%H%M%S')}",
            code=code,
            action="sell",
            price=price,
            quantity=quantity,
            message=f"模拟卖出 {name} 成功",
            timestamp=datetime.datetime.now().isoformat(),
        )


# ── RPA executor (real East Money paper trading) ────────────────────

class RPATradeExecutor(BaseTradeExecutor):
    """Controls East Money paper trading via PyAutoGUI + OCR.

    WARNING: This is platform-dependent and fragile by design.
    Requires: East Money 模拟盘 running in a browser window.
    Calibration needed for each machine's screen resolution.
    """

    def __init__(self):
        self._calibrated = False
        self._buy_button = None    # (x, y) screen coordinates
        self._code_input = None
        self._price_input = None
        self._quantity_input = None
        self._confirm_button = None

    def calibrate(self):
        """Locate key UI elements on screen. Call once before trading."""
        try:
            import pyautogui
            # These coordinates need to be calibrated per machine
            # Use: pyautogui.position() to find coordinates interactively
            print("[RPA] Calibration mode: move mouse to each element and press Enter")
            input('  -> Move mouse to BUY button, press Enter...')
            self._buy_button = pyautogui.position()
            input('  -> Move mouse to CODE input, press Enter...')
            self._code_input = pyautogui.position()
            input('  -> Move mouse to PRICE input, press Enter...')
            self._price_input = pyautogui.position()
            input('  -> Move mouse to QUANTITY input, press Enter...')
            self._quantity_input = pyautogui.position()
            input('  -> Move mouse to CONFIRM button, press Enter...')
            self._confirm_button = pyautogui.position()
            self._calibrated = True
            print(f"[RPA] Calibrated: buy={self._buy_button}, code={self._code_input}, "
                  f"price={self._price_input}, qty={self._quantity_input}, confirm={self._confirm_button}")
        except ImportError:
            print("[RPA] pyautogui not installed. Run: pip install pyautogui")
            self._calibrated = False

    def buy(self, code: str, name: str, price: float, quantity: int = 100) -> ExecutionResult:
        if not self._calibrated:
            return ExecutionResult(False, "", code, "buy", price, quantity,
                                   "RPA 未校准，请先运行 calibrate()", "")

        try:
            import pyautogui
            import time

            # Click buy button, fill form, confirm
            pyautogui.click(self._buy_button)
            time.sleep(0.3)
            pyautogui.click(self._code_input)
            pyautogui.write(code, interval=0.05)
            time.sleep(0.2)
            pyautogui.click(self._price_input)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(str(price), interval=0.05)
            time.sleep(0.2)
            pyautogui.click(self._quantity_input)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(str(quantity), interval=0.05)
            time.sleep(0.2)
            pyautogui.click(self._confirm_button)

            # TODO: OCR to verify fill confirmation
            order_id = f"RPA-B-{datetime.datetime.now().strftime('%H%M%S')}"
            print(f"[RPA] Buy order submitted: {name}({code}) @ {price} x {quantity}")

            return ExecutionResult(
                success=True, order_id=order_id, code=code, action="buy",
                price=price, quantity=quantity,
                message=f"RPA 买入 {name} 已提交", timestamp=datetime.datetime.now().isoformat(),
            )
        except Exception as e:
            return ExecutionResult(False, "", code, "buy", price, quantity, str(e), "")

    def sell(self, code: str, name: str, price: float, quantity: int) -> ExecutionResult:
        if not self._calibrated:
            return ExecutionResult(False, "", code, "sell", price, quantity,
                                   "RPA 未校准", "")

        try:
            import pyautogui
            import time

            pyautogui.click(self._buy_button)  # Same flow, different tab
            time.sleep(0.3)
            pyautogui.click(self._code_input)
            pyautogui.write(code, interval=0.05)
            time.sleep(0.2)
            pyautogui.click(self._price_input)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(str(price), interval=0.05)
            time.sleep(0.2)
            pyautogui.click(self._quantity_input)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(str(quantity), interval=0.05)
            time.sleep(0.2)
            pyautogui.click(self._confirm_button)

            order_id = f"RPA-S-{datetime.datetime.now().strftime('%H%M%S')}"
            return ExecutionResult(
                success=True, order_id=order_id, code=code, action="sell",
                price=price, quantity=quantity,
                message=f"RPA 卖出 {name} 已提交", timestamp=datetime.datetime.now().isoformat(),
            )
        except Exception as e:
            return ExecutionResult(False, "", code, "sell", price, quantity, str(e), "")


# ── Factory ─────────────────────────────────────────────────────────

_executor: Optional[BaseTradeExecutor] = None


def get_executor() -> BaseTradeExecutor:
    """Return the configured executor (mock by default for safety)."""
    global _executor
    if _executor is None:
        mode = getattr(settings, "execution_mode", "mock")
        if mode == "rpa":
            _executor = RPATradeExecutor()
            print("[Executor] Using RPA mode (real screen automation)")
        else:
            _executor = MockTradeExecutor()
            print("[Executor] Using MOCK mode (simulated execution)")
    return _executor
