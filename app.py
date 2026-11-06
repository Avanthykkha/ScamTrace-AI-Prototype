from datetime import timedelta

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="ScamTrace AI | Financial Intelligence", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {font-family: 'Manrope', sans-serif;}
.stApp {background: #0b1017; color: #e6edf5;}
[data-testid="stSidebar"] {background: #101822; border-right: 1px solid #202d3b;}
.block-container {padding-top: 1.7rem; max-width: 1500px;}
.eyebrow {color:#65d6ad; font:500 11px 'DM Mono',monospace; letter-spacing:.14em; text-transform:uppercase;}
.hero {padding: 18px 0 12px;}
.hero h1 {font-size:36px; letter-spacing:-1.5px; margin:4px 0 6px; color:#f4f7fb;}
.hero p {color:#8fa0b2; font-size:14px; margin:0;}
div[data-testid="stMetric"] {background:#111a24; border:1px solid #202d3b; padding:15px 17px; border-radius:12px;}
div[data-testid="stMetricLabel"] {color:#8fa0b2;}
div[data-testid="stMetricValue"] {color:#f4f7fb;}
.notice {padding:12px 15px; border:1px solid #263c4b; border-left:3px solid #65d6ad; background:#101b24; border-radius:8px; color:#aab8c7; font-size:12px;}
.case-card {padding:16px; background:#111a24; border:1px solid #253343; border-radius:12px; margin:7px 0;}
.case-id {font:500 11px 'DM Mono',monospace; color:#65d6ad; letter-spacing:.08em;}
.case-title {font-weight:700; font-size:16px; margin:5px 0; color:#eaf0f7;}
.muted {color:#8fa0b2; font-size:12px;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_signals():
    # Entirely fictional, bank-side signals prepared for this demonstration.
    rows = [
        ("ST-001", "09:00:00", "Northstar Bank", "NS-1042", "Harbor Bank", "HB-2201", 850, "Card transfer", False),
        ("ST-002", "09:06:00", "Harbor Bank", "HB-2201", "Harbor Bank", "HB-2208", 420, "Instant transfer", False),
        ("ST-003", "09:14:00", "Cedar Bank", "CD-3010", "Northstar Bank", "NS-1184", 1200, "Account transfer", False),
        ("ST-004", "09:23:00", "Northstar Bank", "NS-1199", "Cedar Bank", "CD-3022", 260, "Card transfer", False),
        ("ST-005", "10:00:00", "Northstar Bank", "NS-VICTIM", "Northstar Bank", "NS-4401", 48000, "Instant transfer", True),
        ("ST-006", "10:01:10", "Northstar Bank", "NS-4401", "Harbor Bank", "HB-7720", 45500, "Instant transfer", True),
        ("ST-007", "10:02:05", "Harbor Bank", "HB-7720", "Cedar Bank", "CD-8831", 43800, "Instant transfer", True),
        ("ST-008", "10:03:00", "Cedar Bank", "CD-8831", "Cedar Bank", "CD-9912", 42000, "Cash-out transfer", True),
        ("ST-009", "10:02:40", "Harbor Bank", "HB-7720", "Northstar Bank", "NS-4418", 3200, "Instant transfer", True),
        ("ST-010", "10:07:20", "Northstar Bank", "NS-4418", "Cedar Bank", "CD-9920", 3000, "Instant transfer", True),
        ("ST-011", "10:21:00", "Cedar Bank", "CD-3051", "Harbor Bank", "HB-2110", 670, "Card transfer", False),
        ("ST-012", "10:33:00", "Northstar Bank", "NS-1188", "Cedar Bank", "CD-3090", 1450, "Account transfer", False),
        ("ST-013", "10:42:00", "Harbor Bank", "HB-2911", "Northstar Bank", "NS-1882", 940, "Card transfer", False),
        ("ST-014", "10:51:00", "Cedar Bank", "CD-3702", "Northstar Bank", "NS-2018", 1800, "Account transfer", False),
    ]
    columns = ["Signal ID", "Time", "From bank", "From account", "To bank", "To account", "Amount (₹)", "Rail", "Scenario label"]
    frame = pd.DataFrame(rows, columns=columns)
    frame["Time"] = pd.to_datetime("2026-10-16 " + frame["Time"])
    return frame


def score_network(data):
    graph = nx.DiGraph()
    account_bank = {}
    for row in data.itertuples(index=False):
        graph.add_node(row[3])
        graph.add_node(row[5])
        graph.add_edge(row[3], row[5], signal=row[0], amount=row[6], time=row[1])
        account_bank[row[3]] = row[2]
        account_bank[row[5]] = row[4]

    scores, explanations = {}, {}
    for account in graph.nodes:
        incoming = data[data["To account"] == account]
        outgoing = data[data["From account"] == account]
        score, why = 0, []
        if len(outgoing) >= 2:
            score += 15
            why.append("Multiple outgoing transfers")
        if len(incoming) and len(outgoing):
            score += 15
            why.append("Receives and forwards funds")
        quick = any(0 <= (out_time - in_time).total_seconds() <= 600
                    for in_time in incoming["Time"] for out_time in outgoing["Time"])
        if quick:
            score += 35
            why.append("Funds forwarded within 10 minutes")
        involved = pd.concat([incoming["Amount (₹)"], outgoing["Amount (₹)"]])
        if not involved.empty and involved.max() >= 20000:
            score += 20
            why.append("Involved in a high-value transfer")
        banks = set(incoming["From bank"]) | set(incoming["To bank"]) | set(outgoing["From bank"]) | set(outgoing["To bank"])
        if len(banks) >= 3:
            score += 15
            why.append("Connected activity spans three banks")
        scores[account] = min(score, 100)
        explanations[account] = why or ["No strong pattern in the available demo signals"]
    return graph, scores, explanations, account_bank


def money(value):
    return f"₹{value:,.0f}"


signals = load_signals()
graph, scores, explanations, account_bank = score_network(signals)
threshold = st.sidebar.slider("Investigation alert threshold", 0, 100, 45, 5)
min_amount = st.sidebar.number_input("Minimum transfer value", min_value=0, max_value=int(signals["Amount (₹)"].max()), value=0, step=1000, format="%d")
window = signals[signals["Amount (₹)"] >= min_amount].copy()
graph, scores, explanations, account_bank = score_network(window)
alerts = sorted([(a, value) for a, value in scores.items() if value >= threshold], key=lambda item: item[1], reverse=True)

st.markdown("""
<div class="hero"><div class="eyebrow">Cross-institution intelligence · Synthetic demonstration</div>
<h1>ScamTrace <span style="color:#65d6ad">AI</span></h1>
<p>A shared intelligence layer for authorized financial investigations.</p></div>
<div class="notice">SIMULATED ENVIRONMENT &nbsp;·&nbsp; Banks retain their source records in this concept. This screen uses fictional, minimized signals. Alerts are heuristic leads for human review; they are not proof of fraud or instructions to restrict payments.</div>
""", unsafe_allow_html=True)

overview, trail_tab, triage_tab, signals_tab = st.tabs(["◈  Command center", "⌁  Trace a network", "＋  Transaction triage", "▤  Signal ledger"])

with overview:
    st.write("")
    a, b, c, d = st.columns(4)
    a.metric("Signals in view", f"{len(window):,}")
    b.metric("Participating institutions", f"{pd.concat([window['From bank'], window['To bank']]).nunique()}")
    c.metric("Accounts connected", f"{graph.number_of_nodes():,}")
    d.metric("Priority accounts", f"{len(alerts):,}", help="Accounts whose heuristic score meets the selected threshold")

    left, right = st.columns([1.05, 1])
    with left:
        st.subheader("Investigation queue")
        if alerts:
            alert_rows = [{"Priority": "HIGH" if value >= 70 else "REVIEW", "Account": account,
                           "Institution": account_bank.get(account, "—"), "Score": f"{value}/100",
                           "Evidence signals": "; ".join(explanations[account])} for account, value in alerts]
            st.dataframe(pd.DataFrame(alert_rows), use_container_width=True, hide_index=True, height=300)
        else:
            st.info("No accounts meet the current threshold. Adjust the threshold or value filter.")
    with right:
        st.subheader("Illustrative scam pathway")
        st.markdown('<div class="case-card"><div class="case-id">CASE ST-2026-014 · OPEN FOR REVIEW</div><div class="case-title">Rapid cross-bank pass-through</div><div class="muted">Northstar Bank → Harbor Bank → Cedar Bank<br>₹48,000 observed across a 3-minute sequence<br>6 linked accounts · 3 participating institutions</div></div>', unsafe_allow_html=True)
        st.write("**Lead account: `HB-7720`**")
        st.write(" · ".join(explanations.get("HB-7720", ["No current evidence"])))
        st.caption("Scores are transparent demo rules, not a trained or validated fraud model.")

    st.subheader("What this prototype demonstrates")
    x, y, z = st.columns(3)
    x.markdown("**1 · Receive permitted signals**\n\nInstitutions share a minimal, simulated transfer signal with a central intelligence layer.")
    y.markdown("**2 · Connect activity**\n\nGraph analysis links accounts and surfaces rapid pass-through patterns across institutions.")
    z.markdown("**3 · Support investigators**\n\nA human reviewer gets a timeline, linked accounts, and plain-language reasons to prioritize follow-up.")

with trail_tab:
    st.subheader("Follow the movement of funds")
    st.caption("Select an account to inspect its connected component and the signals that form the path.")
    candidates = sorted(graph.nodes)
    selected = st.selectbox("Starting account", candidates, index=candidates.index("NS-VICTIM") if "NS-VICTIM" in candidates else 0)
    component = nx.node_connected_component(graph.to_undirected(), selected) if selected in graph else set()
    subgraph = graph.subgraph(component)
    rows = window[(window["From account"].isin(component)) & (window["To account"].isin(component))].sort_values("Time")
    details, chart = st.columns([0.8, 1.5])
    with details:
        st.metric("Account risk score", f"{scores.get(selected, 0)}/100")
        st.write("**Evidence**")
        for item in explanations.get(selected, []):
            st.write(f"• {item}")
        st.write(f"**Connected accounts:** {len(component)}")
        st.write(f"**Institutions in component:** {len({account_bank.get(node) for node in component})}")
    with chart:
        pos = nx.spring_layout(subgraph, seed=7, k=1.05)
        ex, ey, hover = [], [], []
        for row in rows.itertuples(index=False):
            x0, y0 = pos[row[3]]; x1, y1 = pos[row[5]]
            ex += [x0, x1, None]; ey += [y0, y1, None]
            hover.append(f"{row[0]} · {money(row[6])}")
        edge_trace = go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=1.5, color="#405468"), hoverinfo="skip")
        nx_, ny_, labels, colors, sizes, node_hover = [], [], [], [], [], []
        for node in subgraph.nodes:
            x0, y0 = pos[node]
            nx_.append(x0); ny_.append(y0); labels.append(node)
            colors.append("#ff6b6b" if scores.get(node, 0) >= threshold else ("#65d6ad" if node == selected else "#4e8fcb"))
            sizes.append(27 if scores.get(node, 0) >= threshold else 19)
            node_hover.append(f"{node}<br>{account_bank.get(node, 'Unknown institution')}<br>Risk score: {scores.get(node, 0)}/100<br>" + "<br>".join(explanations.get(node, [])))
        node_trace = go.Scatter(x=nx_, y=ny_, mode="markers+text", text=labels, textposition="bottom center", hovertext=node_hover, hoverinfo="text", marker=dict(size=sizes, color=colors, line=dict(width=1, color="#dce8f2")))
        fig = go.Figure([edge_trace, node_trace])
        fig.update_layout(height=480, paper_bgcolor="#0b1017", plot_bgcolor="#0b1017", font_color="#b8c5d1", showlegend=False, margin=dict(l=10, r=10, t=15, b=10), xaxis=dict(visible=False), yaxis=dict(visible=False))
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("**Chronology**")
    chronology = rows[["Time", "Signal ID", "From bank", "From account", "To bank", "To account", "Amount (₹)", "Rail"]].copy()
    chronology["Time"] = chronology["Time"].dt.strftime("%H:%M:%S")
    st.dataframe(chronology, use_container_width=True, hide_index=True)

with triage_tab:
    st.subheader("Proposed transaction risk check")
    st.caption("A local what-if check over the synthetic signals already in this demo. It does not contact a bank or control a payment.")
    lcol, rcol = st.columns([0.8, 1.2])
    with lcol:
        from_account = st.text_input("Origin account", value="NS-NEW-01")
        origin_bank = st.selectbox("Origin institution", sorted(window["From bank"].unique()))
        to_account = st.text_input("Destination account", value="HB-7720")
        destination_bank = st.selectbox("Destination institution", sorted(window["To bank"].unique()), index=1 if len(window["To bank"].unique()) > 1 else 0)
        amount = st.number_input("Proposed amount (₹)", min_value=0, value=45000, step=500)
        if st.button("Assess proposed transfer", type="primary", use_container_width=True):
            st.session_state["last_triage"] = {"from_account": from_account, "origin_bank": origin_bank, "to_account": to_account, "destination_bank": destination_bank, "amount": amount}
    with rcol:
        proposal = st.session_state.get("last_triage")
        if proposal:
            dest_score = scores.get(proposal["to_account"], 0)
            triage_score = min(100, dest_score + (20 if proposal["amount"] >= 20000 else 0) + (15 if proposal["origin_bank"] != proposal["destination_bank"] else 0))
            level = "Elevated review signal" if triage_score >= 45 else "No strong demo signal"
            st.metric("Illustrative risk indicator", f"{triage_score}/100", level)
            st.write(f"**Route:** {proposal['origin_bank']} `{proposal['from_account']}` → {proposal['destination_bank']} `{proposal['to_account']}`")
            reasons = []
            if dest_score:
                reasons.append(f"Destination account has a current network score of {dest_score}/100")
            if proposal["amount"] >= 20000:
                reasons.append("Proposed amount meets the demo high-value rule")
            if proposal["origin_bank"] != proposal["destination_bank"]:
                reasons.append("Transfer crosses institutions")
            if not reasons:
                reasons.append("No configured high-risk demo indicators were matched")
            st.write("**Matched signals**")
            for reason in reasons:
                st.write(f"• {reason}")
            st.info("In a real deployment, the participating institution would decide any verification or payment action under its own approved procedures.")
        else:
            st.markdown('<div class="case-card"><div class="case-id">DECISION SUPPORT · HUMAN REVIEW</div><div class="case-title">Assess a proposed transfer</div><div class="muted">The illustrative score checks destination network exposure, transfer value, and cross-institution movement. It is not a production prediction.</div></div>', unsafe_allow_html=True)

with signals_tab:
    st.subheader("Shared signal ledger")
    bank_filter = st.selectbox("Institution involved", ["All institutions"] + sorted(set(window["From bank"]) | set(window["To bank"])))
    ledger = window.copy()
    if bank_filter != "All institutions":
        ledger = ledger[(ledger["From bank"] == bank_filter) | (ledger["To bank"] == bank_filter)]
    ledger["Time"] = ledger["Time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(ledger.drop(columns=["Scenario label"]), use_container_width=True, hide_index=True)
    csv = ledger.drop(columns=["Scenario label"]).to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered signals (CSV)", csv, "scamtrace_synthetic_signals.csv", "text/csv")
    st.caption("Scenario labels are used only to construct this fictional demonstration; they are omitted from the investigator view and download.")

st.divider()
st.caption("ScamTrace AI · Datathon prototype · Central intelligence concept with fictional data. No real bank integrations, customer records, trained model, or payment controls.")
