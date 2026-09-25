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

    def fetch_data(self, pair="EUR/USD", interval="15min", outputsize=100) -> pd.DataFrame:
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
            asian_high = round(df['High'].iloc[-24:].max(), 5)
            asian_low = round(df['Low'].iloc[-24:].min(), 5)

        yesterday_df = df[df.index.date < today]
        if not yesterday_df.empty:
            last_date = yesterday_df.index.date.max()
            last_candles = yesterday_df[yesterday_df.index.date == last_date]
            pdh = round(last_candles['High'].max(), 5)
            pdl = round(last_candles['Low'].min(), 5)
        else:
            pdh, pdl = asian_high, asian_low

        curr_price = round(df['Close'].iloc[-1], 5)
        return {
            "current_price": curr_price,
            "asian_high": asian_high,
            "asian_low": asian_low,
            "pdh": pdh,
            "pdl": pdl
        }

    def scan_pair(self, pair: str, macro_report: dict) -> dict:
        df = self.fetch_data(pair=pair, interval="15min", outputsize=100)
        if df.empty or len(df) < 35:
            return {"status": "NO_DATA", "candle": None}

        levels = self.get_session_liquidity(df)
        curr = levels["current_price"]
        macro_score = macro_report.get("macro_score", 0)

        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        recent = df.iloc[-8:]

        setup = None

        # Calibrated to 1.5 so valid momentum trades are permitted
        if macro_score <= -1.5:
            broke_below = (recent["Close"] < levels["asian_low"]).any()
            momentum_down = curr < df["EMA20"].iloc[-1] and df["EMA20"].iloc[-1] < df["EMA50"].iloc[-1]

            if broke_below and momentum_down:
                entry = curr
                sl_price = round(df["EMA20"].iloc[-1] + (12 * self.pip_size), 5)
                risk_pips = round(abs(sl_price - entry) / self.pip_size, 1)

                if 8.0 <= risk_pips <= 30.0:
                    tp1 = round(entry - (risk_pips * 1.5 * self.pip_size), 5)
                    tp2 = round(entry - (risk_pips * 2.5 * self.pip_size), 5)

                    setup = {
                        "pair": pair,
                        "signal": "SELL MARKET",
                        "direction": "BEARISH",
                        "reason": f"Asian Low Breakout on {pair} + Macro Trend Confluence ({macro_score}/5)",
                        "entry_zone": f"{entry:.5f}",
                        "stop_loss": f"{sl_price:.5f}",
                        "sl_pips": risk_pips,
                        "tp1": f"{tp1:.5f}",
                        "tp2": f"{tp2:.5f}",
                        "risk_reward": "1:2.5"
                    }

        elif macro_score >= 1.5:
            broke_above = (recent["Close"] > levels["asian_high"]).any()
            momentum_up = curr > df["EMA20"].iloc[-1] and df["EMA20"].iloc[-1] > df["EMA50"].iloc[-1]

            if broke_above and momentum_up:
                entry = curr
                sl_price = round(df["EMA20"].iloc[-1] - (12 * self.pip_size), 5)
                risk_pips = round(abs(entry - sl_price) / self.pip_size, 1)

                if 8.0 <= risk_pips <= 30.0:
                    tp1 = round(entry + (risk_pips * 1.5 * self.pip_size), 5)
                    tp2 = round(entry + (risk_pips * 2.5 * self.pip_size), 5)

                    setup = {
                        "pair": pair,
                        "signal": "BUY MARKET",
                        "direction": "BULLISH",
                        "reason": f"Asian High Breakout on {pair} + Macro Trend Confluence (+{macro_score}/5)",
                        "entry_zone": f"{entry:.5f}",
                        "stop_loss": f"{sl_price:.5f}",
                        "sl_pips": risk_pips,
                        "tp1": f"{tp1:.5f}",
                        "tp2": f"{tp2:.5f}",
                        "risk_reward": "1:2.5"
                    }

        latest_candle = {"High": float(df["High"].iloc[-1]), "Low": float(df["Low"].iloc[-1])}
        return {
            "status": "READY",
            "pair": pair,
            "levels": levels,
            "active_setup": setup,
            "candle": latest_candle
        }
