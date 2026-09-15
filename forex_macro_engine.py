import os
import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")

class ForexMacroEngine:
    def __init__(self):
        self.dxy_symbol = "DX-Y.NYB"
        self.us10y_symbol = "^TNX"
        self.sp500_symbol = "^GSPC"  # Risk appetite proxy

    def get_dxy_trend(self) -> dict:
        """Analyzes DXY momentum (Dollar strength/weakness)."""
        try:
            dxy = yf.Ticker(self.dxy_symbol)
            df = dxy.history(period="5d", interval="1h")
            if df.empty:
                return {"trend": "UNKNOWN", "score": 0, "price": 0.0}

            curr = df["Close"].iloc[-1]
            ema20 = df["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
            prior = df["Close"].iloc[-5]

            # If DXY is falling, it is BULLISH for EURUSD & GBPUSD
            if curr < ema20 and curr < prior:
                return {"trend": "BEARISH (Falling)", "score": 2, "price": round(curr, 2)}
            elif curr > ema20 and curr > prior:
                return {"trend": "BULLISH (Rising)", "score": -2, "price": round(curr, 2)}
            else:
                return {"trend": "NEUTRAL", "score": 0, "price": round(curr, 2)}
        except Exception as e:
            return {"trend": f"ERROR: {e}", "score": 0, "price": 0.0}

    def get_us10y_trend(self) -> dict:
        """Analyzes US 10Y Yield momentum."""
        try:
            tnx = yf.Ticker(self.us10y_symbol)
            df = tnx.history(period="5d", interval="1h")
            if df.empty:
                return {"trend": "UNKNOWN", "score": 0, "yield": 0.0}

            curr = df["Close"].iloc[-1]
            ema20 = df["Close"].ewm(span=20, adjust=False).mean().iloc[-1]

            # High US yields favor the Dollar (Bearish for EUR & GBP)
            if curr > ema20:
                return {"trend": "BULLISH (Yields Rising)", "score": -1, "yield": round(curr, 2)}
            else:
                return {"trend": "BEARISH (Yields Falling)", "score": 1, "yield": round(curr, 2)}
        except Exception as e:
            return {"trend": f"ERROR: {e}", "score": 0, "yield": 0.0}

    def get_risk_sentiment(self) -> dict:
        """Analyzes S&P 500 to gauge Global Risk-On vs. Risk-Off."""
        try:
            spx = yf.Ticker(self.sp500_symbol)
            df = spx.history(period="3d", interval="1h")
            if df.empty:
                return {"sentiment": "NEUTRAL", "score": 0}

            curr = df["Close"].iloc[-1]
            prior_day_close = df["Close"].iloc[-8]

            # Risk-On is heavily Bullish for GBPUSD, mild Bullish for EURUSD
            if curr > prior_day_close:
                return {"sentiment": "RISK-ON (Equities Green)", "score": 1}
            else:
                return {"sentiment": "RISK-OFF (Equities Red)", "score": -1}
        except Exception as e:
            return {"sentiment": "NEUTRAL", "score": 0}

    def calculate_pair_bias(self, pair="EUR/USD") -> dict:
        """Calculates specific directional bias for EUR/USD or GBP/USD."""
        dxy = self.get_dxy_trend()
        us10y = self.get_us10y_trend()
        risk = self.get_risk_sentiment()

        # DXY has massive 60% weight on EUR/USD
        if pair == "EUR/USD":
            total_score = (dxy["score"] * 1.5) + us10y["score"] + (risk["score"] * 0.5)
        else: # GBP/USD is highly sensitive to risk sentiment
            total_score = dxy["score"] + us10y["score"] + (risk["score"] * 1.5)

        if total_score >= 2.0:
            bias = "STRONG BULLISH"
            directive = f"LOOK FOR {pair} LONGS (Sweep of Asian Lows)"
        elif total_score > 0:
            bias = "MILD BULLISH"
            directive = f"BULLISH BIAS (Exercise caution around daily highs)"
        elif total_score == 0:
            bias = "NEUTRAL / RANGE"
            directive = "STAND BY / TRADE SESSION BOUNDARIES"
        elif total_score >= -2.0:
            bias = "MILD BEARISH"
            directive = f"BEARISH BIAS (Exercise caution around daily lows)"
        else:
            bias = "STRONG BEARISH"
            directive = f"LOOK FOR {pair} SHORTS (Sweep of Asian Highs)"

        return {
            "pair": pair,
            "macro_score": round(total_score, 1),
            "macro_bias": bias,
            "directive": directive,
            "dxy": dxy,
            "us10y": us10y,
            "risk_sentiment": risk
        }

if __name__ == "__main__":
    print("\n--- Scanning Macro Drivers for Forex Majors ---")
    engine = ForexMacroEngine()
    eur_rep = engine.calculate_pair_bias("EUR/USD")
    gbp_rep = engine.calculate_pair_bias("GBP/USD")

    print(f"\n🇪🇺 EUR/USD Bias: {eur_rep['macro_bias']} (Score: {eur_rep['macro_score']})")
    print(f"   Directive:    {eur_rep['directive']}")
    print(f"\n🇬🇧 GBP/USD Bias: {gbp_rep['macro_bias']} (Score: {gbp_rep['macro_score']})")
    print(f"   Directive:    {gbp_rep['directive']}")
    print(f"--------------------------------------------------")
    print(f"DXY Index:       {eur_rep['dxy']['price']} | {eur_rep['dxy']['trend']}")
    print(f"US 10Y Yield:    {eur_rep['us10y']['yield']}% | {eur_rep['us10y']['trend']}")
    print(f"Market Sentiment:{eur_rep['risk_sentiment']['sentiment']}\n")