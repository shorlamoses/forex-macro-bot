import time
from datetime import datetime, timezone
from forex_macro_engine import ForexMacroEngine
from forex_smc_engine import ForexSMCEngine
from forex_telegram import ForexTelegramNotifier

class ForexSentinel:
    def __init__(self):
        self.macro = ForexMacroEngine()
        self.smc = ForexSMCEngine()
        self.notifier = ForexTelegramNotifier()

        self.last_briefing_date = None
        self.last_bias = {"EUR/USD": None, "GBP/USD": None}
        self.last_signal_keys = {"EUR/USD": None, "GBP/USD": None}

    def get_session_context(self) -> tuple:
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour

        # London (07:00-11:00 UTC / 08:00-12:00 WAT) & NY (12:00-16:00 UTC / 13:00-17:00 WAT)
        if (7 <= hour < 11) or (12 <= hour < 16):
            return True, "Active Killzone", 180  # 3 minutes
        elif 6 <= hour < 18:
            return True, "Regular Market Hours", 300  # 5 minutes
        else:
            return False, "Asian / Off-Hours", 600  # 10 minutes

    def check_daily_briefing(self, eur_rep: dict, gbp_rep: dict):
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        if self.last_briefing_date != today and now_utc.hour >= 6:
            print("[Alert]: Sending Daily Forex Pre-Market Briefing to Telegram...")
            self.notifier.send_macro_briefing(eur_rep, gbp_rep)
            self.last_briefing_date = today

    def check_macro_shift(self, pair: str, rep: dict):
        new_bias = rep["macro_bias"]
        old_bias = self.last_bias[pair]

        if old_bias is None:
            self.last_bias[pair] = new_bias
            return

        if new_bias != old_bias:
            self.last_bias[pair] = new_bias
            flag = "🇪🇺" if "EUR" in pair else "🇬🇧"
            msg = (
                f"🔄 {flag} <b>{pair} MACRO REGIME SHIFT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Prior Bias:</b> {old_bias}\n"
                f"• <b>New Bias:</b> <b>{new_bias}</b> ({rep['macro_score']}/5)\n"
                f"🎯 <b>Directive:</b> <code>{rep['directive']}</code>"
            )
            self.notifier.send_message(msg)

    def run_cycle(self):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
        _, session_name, _ = self.get_session_context()

        eur_macro = self.macro.calculate_pair_bias("EUR/USD")
        gbp_macro = self.macro.calculate_pair_bias("GBP/USD")

        # 1. Daily Briefing check
        self.check_daily_briefing(eur_macro, gbp_macro)

        # 2. Scan both pairs
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
                    print(f"🚨 [{pair} SETUP TRIGGERED] Pinging Telegram...")
                    self.notifier.send_forex_trade_alert(setup, macro_rep)
                    self.last_signal_keys[pair] = setup_key

    def start(self):
        print("==================================================")
        print("🚀 Autonomous Forex Sentinel Active (EUR/USD & GBP/USD)")
        print("🔋 Dynamic API Budgeting Engaged")
        print("==================================================")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Cycle Error]: {e}")

            _, _, sleep_sec = self.get_session_context()
            time.sleep(sleep_sec)

if __name__ == "__main__":
    sentinel = ForexSentinel()
    sentinel.start()