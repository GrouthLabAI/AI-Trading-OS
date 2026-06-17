# AI Trading OS - Feishu Notification Module
"""
Send trading alerts to Feishu via webhook.

Usage:
    from backend.notify import Notifier
    n = Notifier(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
    await n.send("交易信号", "中航西飞 买入建议")
"""

from __future__ import annotations

import datetime
import httpx

# Your Feishu webhook URL (set in .env)
FEISHU_WEBHOOK = ""


class Notifier:
    """Send messages to Feishu group via webhook."""

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url or FEISHU_WEBHOOK

    async def send_text(self, content: str) -> bool:
        """Send plain text message."""
        if not self.webhook_url:
            print("[Notify] No webhook configured, skipping")
            return False

        payload = {
            "msg_type": "text",
            "content": {"text": content},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(self.webhook_url, json=payload, timeout=10)
            return r.status_code == 200

    async def send_card(self, title: str, fields: dict) -> bool:
        """Send rich card message (for trading signals)."""
        if not self.webhook_url:
            return False

        field_items = []
        for k, v in fields.items():
            field_items.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{k}**: {v}"}
            })

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"📈 {title}"},
                    "template": "green",
                },
                "elements": [
                    {
                        "tag": "div",
                        "fields": field_items,
                    },
                    {
                        "tag": "hr",
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text",
                             "content": f"AI Trading OS · {datetime.datetime.now().strftime('%m-%d %H:%M')}"}
                        ],
                    },
                ],
            },
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(self.webhook_url, json=payload, timeout=10)
            return r.status_code == 200

    async def send_trade_signal(self, code: str, name: str, action: str,
                                price: float, score: int, reason: str) -> bool:
        """Send a formatted trade signal card."""
        emoji = "🔴" if score >= 85 else "🟠" if score >= 70 else "🟡"
        return await self.send_card(
            title=f"{emoji} {action}: {name}({code}) 评分{score}",
            fields={
                "操作": f"**{action}**",
                "价格": f"¥{price}",
                "评分": f"{score}/100",
                "理由": reason,
            },
        )

    async def send_risk_alert(self, alert_type: str, message: str) -> bool:
        """Send a risk alert (red card)."""
        return await self.send_card(
            title=f"⚠️ 风险警报: {alert_type}",
            fields={
                "类型": alert_type,
                "详情": message,
                "建议": "请立即查看 Dashboard",
            },
        )
