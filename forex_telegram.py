import os
import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class ForexTelegramNotifier:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    def send_message(self, text: str) -> bool:
        if not BOT_TOKEN or not CHAT_ID:
            print("[Error]: Missing Telegram credentials in .env")
            return False

        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            res = requests.post(self.base_url, json=payload, timeout=10)
            return res.json().get("ok", False)
        except Exception as e:
            print(f"[Telegram Network Error]: {e}")
            return False

    def send_forex_trade_alert(self, setup: dict, macro_report: dict) -> bool:
        """Sends an actionable EUR/USD or GBP/USD trade blueprint."""
        flag = "🇪🇺" if "EUR" in setup["pair"] else "🇬🇧"
        direction_emoji = "🟢 <b>BUY LIMIT</b>" if setup["direction"] == "BULLISH" else "🔴 <b>SELL LIMIT</b>"

        message = (
            f"🚨 {flag} <b>NEW {setup['pair']} INTRADAY TRADE SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>Order:</b> {direction_emoji}\n"
            f"🧭 <b>Macro Alignment:</b> <code>{macro_report['macro_bias']} ({macro_report['macro_score']}/5)</code>\n"
            f"💡 <b>Reason:</b> <i>{setup['reason']}</i>\n\n"
            f"🎯 <b>EXECUTION BLUEPRINT (MT5):</b>\n"
            f"• <b>Entry Zone:</b> <code>{setup['entry_zone']}</code>\n"
            f"• <b>Stop Loss:</b> <code>{setup['stop_loss']}</code> (<b>{setup['sl_pips']} pips</b>)\n"
            f"• <b>Target 1:</b> <code>{setup['tp1']}</code> (1:2 R:R)\n"
            f"• <b>Target 2:</b> <code>{setup['tp2']}</code> (Session Liquidity)\n"
            f"• <b>Risk-to-Reward:</b> <b>{setup['risk_reward']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Action: Set limit order on MT5. Move SL to breakeven at Target 1.</i>"
        )
        return self.send_message(message)

    def send_macro_briefing(self, eur_rep: dict, gbp_rep: dict):
        """Sends pre-market briefing for both pairs."""
        msg = (
            f"🏛️ <b>MAJOR FOREX PRE-MARKET INTEL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🇪🇺 <b>EUR/USD:</b> <b>{eur_rep['macro_bias']}</b> ({eur_rep['macro_score']}/5)\n"
            f"🎯 <code>{eur_rep['directive']}</code>\n\n"
            f"🇬🇧 <b>GBP/USD:</b> <b>{gbp_rep['macro_bias']}</b> ({gbp_rep['macro_score']}/5)\n"
            f"🎯 <code>{gbp_rep['directive']}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Market Context:</b>\n"
            f"• <b>DXY Index:</b> {eur_rep['dxy']['price']} | <i>{eur_rep['dxy']['trend']}</i>\n"
            f"• <b>US 10Y Yield:</b> {eur_rep['us10y']['yield']}% | <i>{eur_rep['us10y']['trend']}</i>\n"
            f"• <b>Equities Sentiment:</b> <i>{eur_rep['risk_sentiment']['sentiment']}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Forex Autonomous Engine</i>"
        )
        return self.send_message(msg)