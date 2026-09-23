import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from dotenv import load_dotenv

from forex_macro_engine import ForexMacroEngine
from forex_smc_engine import ForexSMCEngine
from forex_telegram import ForexTelegramNotifier

load_dotenv()

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"FOREX_SENTINEL_OK_200")

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

class ForexSentinel:
    def __init__(self):
        self.macro = ForexMacroEngine()
        self.smc = ForexSMCEngine()
        self.notifier = ForexTelegramNotifier()

        self.last_briefing_date = None
        self.last_summary_date = None
        self.last_signal_keys = {"EUR/USD": None, "GBP/USD": None}

        # Daily Trade Ledger
        self.daily_trades = []

    def is_market_open(self) -> tuple:
        """Enforces weekend and daily rollover blackouts."""
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()
        hour = now_utc.hour

        if weekday == 4 and hour >= 21:
            return False, "Weekend (Friday Market Close)"
        if weekday == 5:
            return False, "Weekend (Market Closed)"
        if weekday == 6 and hour < 21:
            return False, "Weekend (Pre-Market Open)"
        if hour == 21:
            return False, "Daily Bank Rollover Blackout"

        return True, "Market Open"

    def update_trade_outcomes(self, pair: str, current_candle: dict):
        high = current_candle["High"]
        low = current_candle["Low"]

        for trade in self.daily_trades:
            if trade["pair"] == pair and trade["status"] == "OPEN":
                if trade["direction"] == "BULLISH":
                    if low <= trade["sl"]:
                        trade["status"] = "HIT_SL"
                    elif high >= trade["tp2"]:
                        trade["status"] = "HIT_TP2"
                    elif high >= trade["tp1"]:
                        trade["status"] = "HIT_TP1"

                elif trade["direction"] == "BEARISH":
                    if high >= trade["sl"]:
                        trade["status"] = "HIT_SL"
                    elif low <= trade["tp2"]:
                        trade["status"] = "HIT_TP2"
                    elif low <= trade["tp1"]:
                        trade["status"] = "HIT_TP1"

    def send_daily_summary(self):
        """Sends daily performance recap at 20:00 UTC (21:00 WAT)."""
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        if self.last_summary_date != today and now_utc.hour >= 20:
            total = len(self.daily_trades)
            if total == 0:
                msg = (
                    f"📊 <b>FOREX DAILY RECAP ({today.strftime('%d %b')})</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💤 <b>Signals Generated:</b> 0\n"
                    f"<i>Clean market structure was not met. Zero forced trades. Capital safe.</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                tp1 = sum(1 for t in self.daily_trades if t["status"] in ["HIT_TP1", "HIT_TP2"])
                tp2 = sum(1 for t in self.daily_trades if t["status"] == "HIT_TP2")
                sl = sum(1 for t in self.daily_trades if t["status"] == "HIT_SL")

                eur_count = sum(1 for t in self.daily_trades if t["pair"] == "EUR/USD")
                gbp_count = sum(1 for t in self.daily_trades if t["pair"] == "GBP/USD")
                win_rate = round((tp1 / total) * 100, 1)

                msg = (
                    f"📊 <b>MAJOR FOREX DAILY PERFORMANCE</b>\n"
                    f"📅 <i>{today.strftime('%A, %d %B %Y')}</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📋 <b>Total Signals:</b> {total} (🇪🇺 EUR: {eur_count} | 🇬🇧 GBP: {gbp_count})\n"
                    f"✅ <b>Hit Target 1:</b> {tp1}\n"
                    f"🏆 <b>Hit Target 2:</b> {tp2}\n"
                    f"❌ <b>Hit Stop Loss:</b> {sl}\n"
                    f"📈 <b>Daily Win Rate:</b> <b>{win_rate}%</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <i>Forex Autonomous Journal</i>"
                )

            self.notifier.send_message(msg)
            self.last_summary_date = today

    def run_cycle(self):
        market_open, reason = self.is_market_open()
        if not market_open:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] Standby: {reason}")
            return

        now_utc = datetime.now(timezone.utc)

        if self.last_briefing_date != now_utc.date():
            self.daily_trades = []

        eur_macro = self.macro.calculate_pair_bias("EUR/USD")
        gbp_macro = self.macro.calculate_pair_bias("GBP/USD")

        # Morning Briefing (07:30 WAT)
        if self.last_briefing_date != now_utc.date() and now_utc.hour >= 6:
            self.notifier.send_macro_briefing(eur_macro, gbp_macro)
            self.last_briefing_date = now_utc.date()

        for pair, macro_rep in [("EUR/USD", eur_macro), ("GBP/USD", gbp_macro)]:
            smc_rep = self.smc.scan_pair(pair, macro_rep)
            if smc_rep.get("status") != "READY":
                continue

            df = self.smc.fetch_data(pair=pair, interval="15min", outputsize=5)
            if not df.empty:
                curr_candle = {"High": df["High"].iloc[-1], "Low": df["Low"].iloc[-1]}
                self.update_trade_outcomes(pair, curr_candle)

            setup = smc_rep.get("active_setup")
            if setup:
                setup_key = f"{pair}_{setup['signal']}_{setup['entry_zone']}"
                if setup_key != self.last_signal_keys[pair]:
                    print(f"🚨 [{pair} SETUP TRIGGERED] Alerting Telegram...")
                    self.notifier.send_forex_trade_alert(setup, macro_rep)
                    self.last_signal_keys[pair] = setup_key

                    try:
                        self.daily_trades.append({
                            "pair": pair,
                            "direction": setup["direction"],
                            "entry": float(setup["entry_zone"]),
                            "sl": float(setup["stop_loss"]),
                            "tp1": float(setup["tp1"]),
                            "tp2": float(setup["tp2"]),
                            "status": "OPEN",
                            "time": now_utc.strftime("%H:%M")
                        })
                    except Exception as e:
                        print(f"[Ledger Error]: {e}")

        # Send Performance Journal at 21:00 WAT
        self.send_daily_summary()

    def start(self):
        print("💱 Autonomous Forex Sentinel Active with Daily Journal")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Cycle Error]: {e}")

            market_open, _ = self.is_market_open()
            sleep_time = 180 if market_open else 900
            time.sleep(sleep_time)

ForexMarketSentinel = ForexSentinel

if __name__ == "__main__":
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    sentinel = ForexSentinel()
    sentinel.start()
