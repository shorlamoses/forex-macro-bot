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

    def fetch_data(self, pair="EUR/USD", interval="5min", outputsize=200) -> pd.DataFrame:
        """Pulls 200 candles (~16.6 hours) to guarantee Asian session is always present."""
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
        """Calculates Asian Range (00:00-06:00 UTC) and Previous Day High/Low."""
        if df.empty:
            return {}

        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        asian_df = df[(df.index.date == today) & (df.index.hour >= 0) & (df.index.hour < 6)]
        if not asian_df.empty:
            asian_high = round(asian_df['High'].max(), 5)
            asian_low = round(asian_df['Low'].min(), 5)
        else:
            # Fallback to earliest candles of the day
            today_candles = df[df.index.date == today]
            asian_high = round(today_candles['High'].iloc[:36].max() if len(today_candles) >= 36 else df['High'].max(), 5)
            asian_low = round(today_candles['Low'].iloc[:36].min() if len(today_candles) >= 36 else df['Low'].min(), 5)

        yesterday_df = df[df.index.date < today]
        if not yesterday_df.empty:
            last_date = yesterday_df.index.date.max()
            last_candles = yesterday_df[yesterday_df.index.date == last_date]
            pdh = round(last_candles['High'].max(), 5)
            pdl = round(last_candles['Low'].min(), 5)
        else:
            pdh = asian_high
            pdl = asian_low

        curr_price = round(df['Close'].iloc[-1], 5)

        return {
            "current_price": curr_price,
            "asian_high": asian_high,
            "asian_low": asian_low,
            "pdh": pdh,
            "pdl": pdl
        }

    def detect_fvg(self, df: pd.DataFrame) -> list:
        """Detects active 3-candle Fair Value Gaps."""
        fvgs = []
        if len(df) < 5:
            return fvgs

        for i in range(len(df) - 20, len(df) - 1):
            c1, c2, c3 = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]

            # Bullish FVG
            if c1['High'] < c3['Low']:
                gap_top = round(c3['Low'], 5)
                gap_bottom = round(c1['High'], 5)
                subsequent_lows = df['Low'].iloc[i+1:].min() if i + 1 < len(df) else 999
                if subsequent_lows > gap_bottom:
                    fvgs.append({"type": "BULLISH_FVG", "top": gap_top, "bottom": gap_bottom})

            # Bearish FVG
            elif c1['Low'] > c3['High']:
                gap_top = round(c1['Low'], 5)
                gap_bottom = round(c3['High'], 5)
                subsequent_highs = df['High'].iloc[i+1:].max() if i + 1 < len(df) else 0
                if subsequent_highs < gap_top:
                    fvgs.append({"type": "BEARISH_FVG", "top": gap_top, "bottom": gap_bottom})
        return fvgs

    def scan_pair(self, pair: str, macro_report: dict) -> dict:
        """Scans for institutional sweeps of Asian High/Low OR PDH/PDL."""
        df = self.fetch_data(pair=pair, outputsize=200)
        if df.empty:
            return {"status": "NO_DATA"}

        levels = self.get_session_liquidity(df)
        fvgs = self.detect_fvg(df)
        curr = levels["current_price"]
        macro_score = macro_report.get("macro_score", 0)

        # Look back 20 candles (~100 minutes) to give ample time for Displacement & FVG Retest
        recent = df.iloc[-20:]

        # Check for sweeps of EITHER Asian Range OR Previous Day Range
        asian_high_swept = recent['High'].max() > levels['asian_high'] and curr < levels['asian_high']
        pdh_swept = recent['High'].max() > levels['pdh'] and curr < levels['pdh']
        high_sweep = asian_high_swept or pdh_swept
        sweep_level_high = levels['pdh'] if pdh_swept else levels['asian_high']

        asian_low_swept = recent['Low'].min() < levels['asian_low'] and curr > levels['asian_low']
        pdl_swept = recent['Low'].min() < levels['pdl'] and curr > levels['pdl']
        low_sweep = asian_low_swept or pdl_swept
        sweep_level_low = levels['pdl'] if pdl_swept else levels['asian_low']

        setup = None

        # ---------------- BEARISH SETUP (SHORTS) ----------------
        if macro_score <= 0 and high_sweep:
            bearish_fvgs = [f for f in fvgs if f["type"] == "BEARISH_FVG"]
            entry_top = bearish_fvgs[-1]["top"] if bearish_fvgs else round(curr + 0.0003, 5)
            entry_bottom = bearish_fvgs[-1]["bottom"] if bearish_fvgs else round(curr + 0.0001, 5)

            sl_price = round(recent['High'].max() + (3 * self.pip_size), 5)
            risk_pips = round(abs(sl_price - entry_top) / self.pip_size, 1)
            tp1 = round(entry_bottom - (risk_pips * 2 * self.pip_size), 5)
            tp2 = levels['asian_low']
            rr = round(abs(entry_bottom - tp2) / ((risk_pips * self.pip_size) or 0.0001), 1)

            reason_str = "PDH Swept" if pdh_swept else "Asian High Swept"
            setup = {
                "pair": pair,
                "signal": "SELL LIMIT",
                "direction": "BEARISH",
                "reason": f"{reason_str} on {pair} + Macro Bearish Alignment",
                "entry_zone": f"{entry_bottom:.5f} - {entry_top:.5f}",
                "stop_loss": f"{sl_price:.5f}",
                "sl_pips": risk_pips,
                "tp1": f"{tp1:.5f}",
                "tp2": f"{tp2:.5f}",
                "risk_reward": f"1:{rr}"
            }

        # ---------------- BULLISH SETUP (LONGS) ----------------
        elif macro_score >= 0 and low_sweep:
            bullish_fvgs = [f for f in fvgs if f["type"] == "BULLISH_FVG"]
            entry_top = bullish_fvgs[-1]["top"] if bullish_fvgs else round(curr - 0.0001, 5)
            entry_bottom = bullish_fvgs[-1]["bottom"] if bullish_fvgs else round(curr - 0.0003, 5)

            sl_price = round(recent['Low'].min() - (3 * self.pip_size), 5)
            risk_pips = round(abs(entry_bottom - sl_price) / self.pip_size, 1)
            tp1 = round(entry_top + (risk_pips * 2 * self.pip_size), 5)
            tp2 = levels['asian_high']
            rr = round(abs(tp2 - entry_top) / ((risk_pips * self.pip_size) or 0.0001), 1)

            reason_str = "PDL Swept" if pdl_swept else "Asian Low Swept"
            setup = {
                "pair": pair,
                "signal": "BUY LIMIT",
                "direction": "BULLISH",
                "reason": f"{reason_str} on {pair} + Macro Bullish Alignment",
                "entry_zone": f"{entry_bottom:.5f} - {entry_top:.5f}",
                "stop_loss": f"{sl_price:.5f}",
                "sl_pips": risk_pips,
                "tp1": f"{tp1:.5f}",
                "tp2": f"{tp2:.5f}",
                "risk_reward": f"1:{rr}"
            }

        return {
            "status": "READY",
            "pair": pair,
            "levels": levels,
            "active_setup": setup,
            "fvgs": fvgs[-3:] if fvgs else []
        }
