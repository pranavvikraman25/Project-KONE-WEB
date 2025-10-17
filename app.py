# app.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO
from datetime import date, timedelta
import subprocess, shlex

# ---------------- Page config ----------------
st.set_page_config(page_title="CKPI Multi-KPI Analyzer", layout="wide")
st.title("Make Trend Analysis for Different Equipments")

# ---------------- Load Custom CSS (KONE Theme) ----------------
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css("assets/style.css")

# ---------------- Developer Badge & Logo ----------------
with st.sidebar:
    try:
        st.image("assets/logo.png", width=160)
    except Exception:
        st.write("")
    st.markdown("### KONE — Maintenance Dashboard")
    
    st.markdown("---")

# ---------------- Thresholds (normalized keys) ----------------
KPI_THRESHOLDS = {
    "doorfriction": (30.0, 50.0),
    "cumulativedoorspeederror": (0.05, 0.08),
    "lockhookclosingtime": (0.2, 0.6),
    "lockhooktime": (0.3, None),
    "maximumforceduringcompress": (5.0, 28.0),
    "landingdoorlockrollerclearance": (None, 0.029)
}

# ---------------- Helpers ----------------
def normalize_text(s: str):
    if s is None: return ""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())

def read_file(uploaded):
    name = uploaded.name.lower()
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded, engine="openpyxl")
    if name.endswith(".xls"):
        return pd.read_excel(uploaded, engine="xlrd")
    if name.endswith(".csv"):
        return pd.read_csv(uploaded)
    if name.endswith(".json"):
        return pd.read_json(uploaded)
    return pd.read_csv(uploaded)

def parse_dates(df, col):
    df[col] = pd.to_datetime(df[col], dayfirst=False, errors="coerce")
    return df

def detect_peaks_lows(values, low_thresh, high_thresh, std_factor=1.0):
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    peaks, lows = [], []
    if n < 3 or np.isnan(arr).all():
        return peaks, lows
    mean, std = np.nanmean(arr), np.nanstd(arr)
    upper_stat, lower_stat = mean + std_factor * std, mean - std_factor * std
    for i in range(1, n-1):
        a, b, c = arr[i-1], arr[i], arr[i+1]
        if np.isnan(b): continue
        if not np.isnan(a) and not np.isnan(c):
            if b > a and b > c and ((high_thresh is not None and b > high_thresh) or b > upper_stat):
                peaks.append(i)
            if b < a and b < c and ((low_thresh is not None and b < low_thresh) or b < lower_stat):
                lows.append(i)
    return peaks, lows

def point_status(value, thresh):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "nodata"
    low, high = thresh
    if low is not None and high is not None:
        return "ok" if low <= value <= high else "corrective"
    if low is None and high is not None:
        return "ok" if value <= high else "corrective"
    if low is not None and high is None:
        return "ok" if value >= low else "corrective"
    return "corrective"

def color_cycle(i):
    palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#7f7f7f"]
    return palette[i % len(palette)]

def df_to_excel_bytes(df_):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df_.to_excel(writer, index=False, sheet_name="Actionable_Report")
    out.seek(0)
    return out

def ollama_summarize(text, model="mistral"):
    try:
        cmd = f"ollama run {model} \"Summarize this maintenance report in 4 bullet points for a manager: {text}\""
        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return None

# ---------------- Upload ----------------
uploaded = st.file_uploader("Upload KPI file (xlsx/xls/csv/json)", type=["xlsx","xls","csv","json"])
if not uploaded:
    st.info("Upload a KPI file to begin. Required columns: eq, ckpi, ckpi_statistics_date, floor, ave")
    st.stop()

try:
    df = read_file(uploaded)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

if df.empty:
    st.error("Uploaded file is empty.")
    st.stop()

cols_lower = {c.lower(): c for c in df.columns}
required = ["ckpi_statistics_date","ave","ckpi","floor","eq"]
for req in required:
    if req not in cols_lower:
        st.error(f"Required column '{req}' not found in file.")
        st.stop()

date_col, ave_col, ckpi_col, floor_col, eq_col = [cols_lower[c] for c in required]
df = parse_dates(df, date_col)
if df[date_col].isna().all():
    st.error("Could not parse any dates. Ensure format mm/dd/yyyy.")
    st.stop()

df["_ckpi_norm"] = df[ckpi_col].astype(str).apply(normalize_text)

# ---------------- Sidebar Filters ----------------
st.sidebar.header("Global Filters")

eq_choices = sorted(df[eq_col].dropna().unique())
selected_eq = st.sidebar.multiselect("Select EQ(s)", eq_choices, default=eq_choices[:2] if eq_choices else [])

floor_choices = sorted(df[floor_col].dropna().unique())
selected_floors = st.sidebar.multiselect("Select Floor(s)", floor_choices, default=floor_choices[:2] if floor_choices else [])

file_kpis = df[["_ckpi_norm", ckpi_col]].drop_duplicates().set_index("_ckpi_norm")[ckpi_col].to_dict()
available_kpis = sorted(list(set(list(KPI_THRESHOLDS.keys()) + list(file_kpis.keys()))))
kpi_display = [file_kpis[k] if k in file_kpis else k for k in available_kpis]
selected_kpis_display = st.sidebar.multiselect("Select KPI(s)", kpi_display, default=kpi_display[:6] if kpi_display else [])
selected_kpis = [normalize_text(s) for s in selected_kpis_display]

st.sidebar.markdown("### Date Range")
preset_range = st.sidebar.selectbox("Quick Select", ["Custom", "Past Week", "Past Month", "Past 3 Months", "Past 6 Months", "Past Year"])
today = date.today()
if preset_range == "Custom":
    start_date, end_date = st.sidebar.date_input("Select Date Range", [df[date_col].min().date(), df[date_col].max().date()])
elif preset_range == "Past Week":
    start_date, end_date = today - timedelta(days=7), today
elif preset_range == "Past Month":
    start_date, end_date = today - timedelta(days=30), today
elif preset_range == "Past 3 Months":
    start_date, end_date = today - timedelta(days=90), today
elif preset_range == "Past 6 Months":
    start_date, end_date = today - timedelta(days=180), today
else:
    start_date, end_date = today - timedelta(days=365), today

std_factor = st.sidebar.slider("Peak/Low Sensitivity", 0.5, 3.0, 1.0, 0.1)

# ---------------- Apply Filters ----------------
mask = (
    df[eq_col].isin(selected_eq) &
    df[floor_col].isin(selected_floors) &
    df["_ckpi_norm"].isin(selected_kpis) &
    (df[date_col].dt.date >= start_date) & (df[date_col].dt.date <= end_date)
)
df_filtered = df[mask].copy()

if df_filtered.empty:
    st.warning("No data after applying filters.")
    st.stop()

df_filtered[ave_col] = pd.to_numeric(df_filtered[ave_col], errors="coerce")

# ---------------- KPI Graphs (Single Column Layout) ----------------
st.markdown("### KPI Trends")

kpi_summary = []

for kpi_norm in selected_kpis:
    kpi_display_name = file_kpis.get(kpi_norm, kpi_norm)
    df_kpi = df_filtered[df_filtered["_ckpi_norm"] == kpi_norm]
    if df_kpi.empty:
        st.info(f"No data for KPI: {kpi_display_name}")
        continue

    st.subheader(f"KPI: {kpi_display_name}")
    fig = go.Figure()
    floors = sorted(df_kpi[floor_col].dropna().unique())
    for i, floor in enumerate(floors):
        df_floor = df_kpi[df_kpi[floor_col] == floor].sort_values(date_col)
        if df_floor.empty: continue
        color = color_cycle(i)
        thresh = KPI_THRESHOLDS.get(kpi_norm, (None, None))
        low_thresh, high_thresh = thresh

        status_colors = [
            "#2ca02c" if point_status(v, thresh) == "ok" else "#ffcc00"
            for v in df_floor[ave_col]
        ]

        fig.add_trace(go.Scatter(
            x=df_floor[date_col],
            y=df_floor[ave_col],
            mode="lines+markers",
            name=f"Floor {floor}",
            line=dict(color=color, width=2),
            marker=dict(size=8, color=status_colors, line=dict(color="#000", width=1)),
            hovertemplate="Date: %{x|%m/%d/%Y}<br>Floor: "+str(floor)+"<br>ave: %{y:.2f}<extra></extra>"
        ))

        peaks, lows = detect_peaks_lows(df_floor[ave_col].values, low_thresh, high_thresh, std_factor)
        if peaks:
            fig.add_trace(go.Scatter(
                x=df_floor[date_col].values[peaks],
                y=df_floor[ave_col].values[peaks],
                mode="markers",
                marker=dict(symbol="triangle-up", color="red", size=11),
                name=f"Peaks (Floor {floor})"
            ))
        if lows:
            fig.add_trace(go.Scatter(
                x=df_floor[date_col].values[lows],
                y=df_floor[ave_col].values[lows],
                mode="markers",
                marker=dict(symbol="triangle-down", color="blue", size=11),
                name=f"Lows (Floor {floor})"
            ))

        kpi_summary.append({
            "kpi": kpi_display_name,
            "floor": floor,
            "peaks": len(peaks),
            "lows": len(lows),
            "rows": len(df_floor)
        })

        # --- Clean CloudView-like Date Axis (no duplicate graph, even spacing) ---
    unique_dates = sorted(df_floor[date_col].dt.date.unique())
    num_dates = len(unique_dates)
    
    # Generate evenly spaced tick indices (like CloudView)
    max_ticks = 10  # around 10–12 ticks max, auto-adjusts later
    tick_positions = np.linspace(0, num_dates - 1, min(max_ticks, num_dates), dtype=int)
    tick_dates = [unique_dates[i] for i in tick_positions]
    
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="ave",
        height=480,
        hovermode="x unified",  # unified hover line, still neat
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        xaxis=dict(
            tickmode="array",
            tickvals=[unique_dates[i] for i in tick_positions],  # even date positions
            ticktext=[d.strftime("%d %b %Y") for d in tick_dates],  # ex: 05 Aug 2025
            tickangle=0,  # perfectly horizontal, like CloudView
            tickfont=dict(size=11, color="#444"),
            showgrid=True,
            gridcolor="#E0E0E0",
            zeroline=False,
            fixedrange=False,
            rangeselector=dict(
                buttons=list([
                    dict(count=7, label="1W", step="day", stepmode="backward"),
                    dict(count=30, label="1M", step="day", stepmode="backward"),
                    dict(count=90, label="3M", step="day", stepmode="backward"),
                    dict(count=180, label="6M", step="day", stepmode="backward"),
                    dict(count=365, label="1Y", step="day", stepmode="backward"),
                    dict(step="all")
                ]),
                x=0.02, xanchor="left", y=1.15, yanchor="top"
            ),
            rangeslider=dict(visible=False)  # ❌ No duplicate mini graph
        ),
        margin=dict(l=40, r=40, t=70, b=80),
        plot_bgcolor="white",
        paper_bgcolor="white"
    )



    st.plotly_chart(fig, use_container_width=True)
    st.markdown("---")

# ---------------- Legend ----------------
st.markdown("**Legend:** 🟢 Within threshold (OK) &nbsp;&nbsp; 🟡 Outside threshold (Corrective) &nbsp;&nbsp; 🔺 Peak &nbsp;&nbsp; 🔻 Low")
st.markdown("---")

# ---------------- Actionable Insights ----------------
st.subheader("⚡ Actionable Insights Report ⚡")

REMEDY_BY_KPI = {
    "doorfriction": "Lubricate guide rails; inspect rollers (Solution 1)",
    "cumulativedoorspeederror": "Check door motor encoder calibration (Solution 2)",
    "lockhookclosingtime": "Inspect lock hook mechanism and wiring",
    "lockhooktime": "Verify actuator response timing",
    "maximumforceduringcompress": "Check coupler alignment settings",
    "landingdoorlockrollerclearance": "Measure roller clearance; replace worn rollers"
}

report_rows = []
for rec in kpi_summary:
    if rec['rows'] == 0:
        continue
    if rec['peaks'] + rec['lows'] > rec['rows'] * 0.2:
        remedy = REMEDY_BY_KPI.get(normalize_text(rec['kpi']), "Follow standard inspection checklist")
        report_rows.append({
            "KPI": rec['kpi'],
            "Floor": rec['floor'],
            "Rows": rec['rows'],
            "Peaks": rec['peaks'],
            "Lows": rec['lows'],
            "Action Needed": "⚠️ High uncertainty → Technician check",
            "Remedy / Reason": remedy
        })

report_df = pd.DataFrame(report_rows)
if not report_df.empty:
    st.dataframe(report_df)
    st.download_button(
        "Download Actionable Report (Excel)",
        data=df_to_excel_bytes(report_df),
        file_name="kpi_actionable_report.xlsx"
    )
    st.markdown("### 🧠 AI Summary (via Ollama)")
    summary_text = ollama_summarize(report_df.to_csv(index=False))
    if summary_text:
        st.write(summary_text)
    else:
        st.info("Ollama not available or returned no summary. Install Ollama for local AI insights.")
else:
    st.info("No action needed for selected filters.")

# ---------------- Footer ----------------
st.markdown("---")
st.caption("© 2025 KONE Internal Dashboard | Developed by PRANAV VIKRAMAN S S")












