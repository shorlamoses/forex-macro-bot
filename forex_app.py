import streamlit as st
import threading
from datetime import datetime

from forex_macro_engine import ForexMacroEngine
from forex_smc_engine import ForexSMCEngine
from forex_telegram import ForexTelegramNotifier
from forex_scanner import ForexSentinel

# Page Configuration
st.set_page_config(
    page_title="Major FX Terminal (EUR/USD & GBP/USD)",
    page_icon="💱",
    layout="wide"
)

# ----------------- AUTONOMOUS CLOUD SENTINEL -----------------
@st.cache_resource
def run_cloud_sentinel():
    sentinel = ForexSentinel()
    worker = threading.Thread(target=sentinel.start, daemon=True)
    worker.start()
    return sentinel

run_cloud_sentinel()

# ----------------- UI DASHBOARD -----------------
st.title("💱 Major Forex Macro & SMC Terminal")
st.caption(f"EUR/USD & GBP/USD Institutional Order Flow | Scanned at: {datetime.utcnow().strftime('%H:%M:%S UTC')}")

# Pair Selector Tab
selected_pair = st.radio("Select Currency Pair:", ["EUR/USD", "GBP/USD"], horizontal=True)
flag = "🇪🇺" if selected_pair == "EUR/USD" else "🇬🇧"

if st.button("🔄 Refresh Market Data"):
    st.rerun()

st.divider()

# Load Data
macro_engine = ForexMacroEngine()
macro_rep = macro_engine.calculate_pair_bias(selected_pair)

smc_engine = ForexSMCEngine()
smc_rep = smc_engine.scan_pair(selected_pair, macro_rep)

# Section 1: Macro
st.subheader(f"🧭 1. {flag} {selected_pair} Macro Drivers")

score = macro_rep["macro_score"]
score_color = "🟢" if score >= 2 else ("🟩" if score > 0 else ("⚪" if score == 0 else ("🟧" if score >= -2 else "🔴")))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Macro Bias", f"{score_color} {macro_rep['macro_bias']}", f"Score: {score}/5")
m2.metric("DXY Index", str(macro_rep['dxy']['price']), macro_rep['dxy']['trend'], delta_color="inverse")
m3.metric("US 10Y Yield", f"{macro_rep['us10y']['yield']}%", macro_rep['us10y']['trend'], delta_color="inverse")
m4.metric("Risk Appetite", macro_rep['risk_sentiment']['sentiment'])

st.info(f"**Institutional Directive:** {macro_rep['directive']}")

st.divider()

# Section 2: SMC Setup
st.subheader(f"🎯 2. {flag} {selected_pair} SMC Structure & Setup")

if smc_rep.get("status") == "READY":
    levels = smc_rep["levels"]
    curr_price = levels["current_price"]

    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Spot Price", f"{curr_price:.5f}")
    l2.metric("Asian Range", f"{levels['asian_low']:.5f} - {levels['asian_high']:.5f}")
    l3.metric("Prev Day Range", f"{levels['pdl']:.5f} - {levels['pdh']:.5f}")
    l4.metric("Active FVGs", f"{len(smc_rep.get('fvgs', []))} detected")

    setup = smc_rep.get("active_setup")
    if setup:
        st.success(f"### 🚨 SETUP TRIGGERED: {setup['signal']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Entry Zone:** `{setup['entry_zone']}`")
        c2.write(f"**Stop Loss:** `{setup['stop_loss']}` ({setup['sl_pips']} pips)")
        c3.write(f"**Target 1 (1:2):** `{setup['tp1']}`")
        c4.write(f"**Target 2 (Liquidity):** `{setup['tp2']}`")
        st.write(f"**Reason:** {setup['reason']}")
    else:
        st.warning(f"⏳ **STATUS: SCANNING.** Monitoring Asian High (`{levels['asian_high']:.5f}`) and Asian Low (`{levels['asian_low']:.5f}`).")

    # Section 3: MT5 Forex Pip & Lot Calculator
    st.divider()
    st.subheader("🧮 3. MT5 Forex Lot Size Calculator")

    calc1, calc2, calc3 = st.columns(3)
    with calc1:
        bal = st.number_input("Account Balance ($)", min_value=10.0, value=1000.0, step=50.0)
    with calc2:
        risk_pct = st.number_input("Risk Per Trade (%)", min_value=0.25, max_value=5.0, value=1.0, step=0.25)
    with calc3:
        default_pips = setup['sl_pips'] if setup else 15.0
        sl_pips = st.number_input("Stop Loss in Pips", min_value=2.0, value=float(default_pips), step=1.0)

    risk_usd = bal * (risk_pct / 100.0)
    # Forex standard: 1.00 lot = $10/pip on EUR/USD and GBP/USD
    # Lot Size = Risk ($) / (SL Pips * 10)
    lot_size = risk_usd / (sl_pips * 10.0)

    st.markdown(f"""
    * **Risk Amount:** `${risk_usd:.2f}`
    * **Recommended MT5 Lot Size:** **`{lot_size:.2f}` Lots** *(at $10/pip standard)*
    """)

st.divider()

# Section 4: Manual Test Push
st.subheader("📱 4. Send Intelligence to Phone")
if st.button("📲 Push Macro Briefing to Telegram"):
    notifier = ForexTelegramNotifier()
    gbp_m = macro_engine.calculate_pair_bias("GBP/USD")
    sent = notifier.send_macro_briefing(macro_rep, gbp_m)
    if sent:
        st.success("✅ Forex macro briefing sent to Telegram!")
    else:
        st.error("❌ Failed. Check bot credentials in .env")