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
    print(f"📡 Forex Sentinel Health Server online on port {port}")
    server.serve_forever()

class ForexSentinel:
    def __init__(self):
        self.macro = ForexMacroEngine()
        self.smc = ForexSMCEngine()
        self.notifier = ForexTelegramNotifier()

        self.last_briefing_date = None
        # Stores simplified bias: "BULLISH", "BEARISH", "NEUTRAL"
        self.last_core_bias = {"EUR/USD": None, "GBP/USD": None}
        self.last_signal_keys = {"EUR/USD": None, "GBP/USD": None}

    def simplify_bias(self, bias_str: str) -> str:
        """Eliminates micro-flickering between Mild and Strong."""
        if "BULLISH" in bias_str:
            return "BULLISH"
        elif "BEARISH" in bias_str:
            return "BEARISH"
        return "NEUTRAL"

    def get_session_context(self) -> tuple:
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        if (7 <= hour < 11) or (12 <= hour < 16):
            return True, "Active Killzone", 180
        elif 6 <= hour < 18:
            return True, "Regular Market Hours", 300
        else:
            return False, "Asian / Off-Hours", 600

    def check_daily_briefing(self, eur_rep: dict, gbp_rep: dict):
        now_utc = datetime.now(timezone.utc)
        if self.last_briefing_date != now_utc.date() and now_utc.hour >= 6:
            print("[Alert]: Dispatching Daily Forex Pre-Market Briefing to Telegram...")
            self.notifier.send_macro_briefing(eur_rep, gbp_rep)
            self.last_briefing_date = now_utc.date()

    def check_macro_shift(self, pair: str, rep: dict):
        current_core = self.simplify_bias(rep["macro_bias"])
        old_core = self.last_core_bias[pair]

        if old_core is None:
            self.last_core_bias[pair] = current_core
            return

        # ONLY ping if the actual directional polarity flips (e.g. Bearish -> Bullish)
        if current_core != old_core:
            self.last_core_bias[pair] = current_core
            flag = "🇪🇺" if "EUR" in pair else "🇬🇧"
            msg = (
                f"🔄 {flag} <b>{pair} MACRO DIRECTION FLIP</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Prior Direction:</b> {old_core}\n"
                f"• <b>New Direction:</b> <b>{current_core}</b> ({rep['macro_score']}/5)\n"
                f"🎯 <b>Directive:</b> <code>{rep['directive']}</code>"
            )
            self.notifier.send_message(msg)

    def run_cycle(self):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
        _, session_name, _ = self.get_session_context()

        eur_macro = self.macro.calculate_pair_bias("EUR/USD")
        gbp_macro = self.macro.calculate_pair_bias("GBP/USD")

        self.check_daily_briefing(eur_macro, gbp_macro)

        for pair, macro_rep in [("EUR/USD", eur_macro), ("GBP/USD", gbp_macro)]:
            self.check_macro_shift(pair, macro_rep)

            smc_rep = self.smc.scan_pair(pair, macro_rep)
            if smc_rep.get("status") != "READY":
                continue

            levels = smc_rep["levels"]
            print(f"[{timestamp}] {session_name} | {pair}: {levels['current_price']} | Bias: {macro_rep['macro_bias']}")

            setup = smc_rep.get("active_setup")
            if setup:
                setup_key = f"{pair}_{setup['signal']}_{setup['entry_zone']}"
                if setup_key != self.last_signal_keys[pair]:
                    print(f"🚨 [{pair} TRADE SIGNAL FOUND] Alerting Telegram...")
                    self.notifier.send_forex_trade_alert(setup, macro_rep)
                    self.last_signal_keys[pair] = setup_key

    def start(self):
        print("==================================================")
        print("💱 Autonomous Forex Sentinel Active (EUR/USD & GBP/USD)")
        print("==================================================")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Forex Scan Error]: {e}")

            _, _, sleep_sec = self.get_session_context()
            time.sleep(sleep_sec)

# Alias so both names import cleanly without error
ForexMarketSentinel = ForexSentinel

if __name__ == "__main__":
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    sentinel = ForexSentinel()
    sentinel.start()
