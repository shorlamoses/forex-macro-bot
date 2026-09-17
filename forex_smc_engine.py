import os
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

class ForexSMCEngine:
    def __init__(self):
        self.api_key = TWELVE_DATA_API_KEY
        self.pip_size = 0.0001

    def fetch_data(self, pair="EUR/USD", interval="15min", outputsize=150) -> pd.DataFrame:
        if not self.api_key:
            return pd.DataFrame()

        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={interval}&outputsize={outputsize}&apikey={self.api_key}"
        try:
            res = requests.get(url, timeout=10)
            data = res.json()
            if "values" not in data:
                return pd.DataFrame()

            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            df = df.sort_index()

            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)

            df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
            return df
        except Exception as e:
            print(f"[Error fetching {pair}]: {e}")
            return pd.DataFrame()

    def get_session_liquidity(self, df: pd.DataFrame) -> dict:
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        asian_df = df[(df.index.date == today) & (df.index.hour >= 0) & (df.index.hour < 6)]
        if not asian_df.empty:
            asian_high = round(asian_df['High'].max(), 5)
            asian_low = round(asian_df['Low'].min(), 5)
        else:
            today_candles = df[df.index.date == today]
            asian_high = round(today_candles['High'].iloc[:24].max() if len(today_candles) >= 24 else df['High'].max(), 5)
            asian_low = round(today_candles['Low'].iloc[:24].min() if len(today_candles) >= 24 else df['Low'].min(), 5)

        yesterday_df = df[df.index.date < today]
        if not yesterday_df.empty:
            last_date = yesterday_df.index.date.max()
            last_candles = yesterday_df[yesterday_df.index.date == last_date]
            pdh = round(last_candles['High'].max(), 5)
            pdl = round(last_candles['Low'].min(), 5)
        else:
            pdh, pdl = asian_high, asian_low

        curr_price = round(df['Close'].iloc[-1], 5)
        return {"current_price": curr_price, "asian_high": asian_high, "asian_low": asian_low, "pdh": pdh, "pdl": pdl}

    def scan_pair(self, pair: str, macro_report: dict) -> dict:
        """Trades London/NY Breakout & Retest in the direction of the Macro trend."""
        df = self.fetch_data(pair=pair, interval="15min", outputsize=120)
        if df.empty or len(df) < 30:
            return {"status": "NO_DATA"}

        levels = self.get_session_liquidity(df)
        curr = levels["current_price"]
        macro_score = macro_report.get("macro_score", 0)

        # 20 EMA for dynamic trend
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        recent = df.iloc[-12:]  # Past 3 hours

        setup = None

        # ---------------- BEARISH BREAKOUT & RETEST ----------------
        # 1. Macro is Bearish
        # 2. Asian Low was broken with displacement (at least 1 candle closed below it)
        # 3. Retest: Current price pulls back to test the broken Asian Low from underneath
        if macro_score <= -1:
            broke_below = (recent["Close"] < levels["asian_low"]).any()
            retesting = abs(curr - levels["asian_low"]) <= (10 * self.pip_size) and curr <= levels["asian_low"] + (3 * self.pip_size)
            below_ema = curr < df["EMA20"].iloc[-1]

            if broke_below and retesting and below_ema:
                entry = curr
                sl_price = round(levels["asian_low"] + (15 * self.pip_size), 5)  # 15 pips above broken low
                risk_pips = round(abs(sl_price - entry) / self.pip_size, 1)
                tp1 = round(entry - (risk_pips * 1.5 * self.pip_size), 5)
                tp2 = round(entry - (risk_pips * 2.5 * self.pip_size), 5)

                setup = {
                    "pair": pair,
                    "signal": "SELL MARKET",
                    "direction": "BEARISH",
                    "reason": f"Asian Low Break & Retest on {pair} + Macro Bearish Alignment",
                    "entry_zone": f"{entry:.5f}",
                    "stop_loss": f"{sl_price:.5f}",
                    "sl_pips": risk_pips,
                    "tp1": f"{tp1:.5f}",
                    "tp2": f"{tp2:.5f}",
                    "risk_reward": "1:2.5"
                }

        # ---------------- BULLISH BREAKOUT & RETEST ----------------
        elif macro_score >= 1:
            broke_above = (recent["Close"] > levels["asian_high"]).any()
            retesting = abs(curr - levels["asian_high"]) <= (10 * self.pip_size) and curr >= levels["asian_high"] - (3 * self.pip_size)
            above_ema = curr > df["EMA20"].iloc[-1]

            if broke_above and retesting and above_ema:
                entry = curr
                sl_price = round(levels["asian_high"] - (15 * self.pip_size), 5)
                risk_pips = round(abs(entry - sl_price) / self.pip_size, 1)
                tp1 = round(entry + (risk_pips * 1.5 * self.pip_size), 5)
                tp2 = round(entry + (risk_pips * 2.5 * self.pip_size), 5)

                setup = {
                    "pair": pair,
                    "signal": "BUY MARKET",
                    "direction": "BULLISH",
                    "reason": f"Asian High Break & Retest on {pair} + Macro Bullish Alignment",
                    "entry_zone": f"{entry:.5f}",
                    "stop_loss": f"{sl_price:.5f}",
                    "sl_pips": risk_pips,
                    "tp1": f"{tp1:.5f}",
                    "tp2": f"{tp2:.5f}",
                    "risk_reward": "1:2.5"
                }

        return {
            "status": "READY",
            "pair": pair,
            "levels": levels,
            "active_setup": setup,
            "fvgs": []
        }
