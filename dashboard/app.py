"""NYC Yellow Taxi dashboard.

Reads two small mart tables built by dbt:
  - fct_trip_summary  (date x hour x weekday x borough x payment grain)
  - fct_zone_metrics  (date x zone grain)

All filters slice these pre-aggregated marts, so queries stay fast no
matter how many months are loaded. Averages are recomputed from stored
sums/counts AFTER filtering, so they are correctly weighted.
"""

from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parents[1]
_FULL = _ROOT / "data" / "warehouse" / "nyc_taxi.duckdb"
_DEPLOY = Path(__file__).resolve().parent / "deploy.duckdb"
DB_PATH = _FULL if _FULL.exists() else _DEPLOY
MARTS_SCHEMA = "main_marts"  # check with: SHOW ALL TABLES (see INSTRUCTIONS.md step 6)

WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

st.set_page_config(page_title="NYC Yellow Taxi Analytics", page_icon="🚕", layout="wide")


@st.cache_resource
def get_connection():
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(ttl=600)
def load_summary() -> pd.DataFrame:
    return get_connection().execute(
        f"SELECT * FROM {MARTS_SCHEMA}.fct_trip_summary"
    ).fetchdf()


@st.cache_data(ttl=600)
def load_zones() -> pd.DataFrame:
    return get_connection().execute(
        f"SELECT * FROM {MARTS_SCHEMA}.fct_zone_metrics"
    ).fetchdf()


summary = load_summary()
summary["pickup_date"] = pd.to_datetime(summary["pickup_date"]).dt.date
zones = load_zones()
zones["pickup_date"] = pd.to_datetime(zones["pickup_date"]).dt.date

# ---------------------------------------------------------------- sidebar
st.sidebar.header("Filters")

min_d, max_d = summary.pickup_date.min(), summary.pickup_date.max()
start = st.sidebar.date_input("From", value=min_d, min_value=min_d, max_value=max_d)
end = st.sidebar.date_input("To", value=max_d, min_value=min_d, max_value=max_d)
if start > end:
    st.sidebar.error("'From' must be on or before 'To'.")
    st.stop()

boroughs = sorted(summary.pickup_borough.unique())
sel_boroughs = st.sidebar.multiselect("Pickup borough", boroughs, default=boroughs)

payments = sorted(summary.payment_type.unique())
sel_payments = st.sidebar.multiselect("Payment type", payments, default=payments)

hour_lo, hour_hi = st.sidebar.select_slider(
    "Pickup hour", options=list(range(24)), value=(0, 23),
    format_func=lambda h: f"{h:02d}:00",
)

# ---------------------------------------------------------------- filtering
f = summary[
    (summary.pickup_date >= start)
    & (summary.pickup_date <= end)
    & summary.pickup_borough.isin(sel_boroughs)
    & summary.payment_type.isin(sel_payments)
    & summary.hour_of_day.between(hour_lo, hour_hi)
]

zf = zones[
    (zones.pickup_date >= start)
    & (zones.pickup_date <= end)
    & zones.borough.isin(sel_boroughs)
]

st.title("NYC Yellow Taxi Analytics")
st.caption(f"{start} → {end} · {len(sel_boroughs)}/{len(boroughs)} boroughs · "
           f"{len(sel_payments)}/{len(payments)} payment types · "
           f"{hour_lo:02d}:00–{hour_hi:02d}:59")

if f.empty:
    st.warning("No data matches the current filters.")
    st.stop()

# ---------------------------------------------------------------- KPIs
trips = int(f.trips.sum())
revenue = float(f.revenue.sum())
avg_fare = revenue / trips
tip_pct = float(f.tip_sum.sum()) / float(f.fare_sum.sum())
avg_dist = float(f.distance_sum.sum()) / trips
avg_dur = float(f.duration_sum.sum()) / trips

def compact(n: float, prefix: str = "") -> str:
    """33_891_042 -> '33.9M', 1_013_450_000 -> '$1.01B' (with prefix)."""
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{prefix}{n / div:.2f}{suffix}"
    return f"{prefix}{n:,.0f}"


k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Trips", compact(trips), help=f"{trips:,}")
k2.metric("Revenue", compact(revenue, "$"), help=f"${revenue:,.0f}")
k3.metric("Avg fare", f"${avg_fare:.2f}")
k4.metric("Avg tip", f"{tip_pct:.1%}")
k5.metric("Avg distance", f"{avg_dist:.1f} mi")
k6.metric("Avg duration", f"{avg_dur:.0f} min")

st.divider()

# ---------------------------------------------------------------- row 1
left, right = st.columns((3, 2))

with left:
    st.subheader("Daily trend")
    metric = st.radio("Metric", ["Trips", "Revenue", "Avg fare"],
                      horizontal=True, label_visibility="collapsed")
    daily = f.groupby("pickup_date", as_index=False).agg(
        trips=("trips", "sum"), revenue=("revenue", "sum")
    )
    daily["avg_fare"] = daily.revenue / daily.trips
    col = {"Trips": "trips", "Revenue": "revenue", "Avg fare": "avg_fare"}[metric]
    fmt = {"trips": ",.0f", "revenue": "$,.0f", "avg_fare": "$.2f"}[col]
    st.altair_chart(
        alt.Chart(daily).mark_area(opacity=0.6, line=True).encode(
            x=alt.X("pickup_date:T", title=None),
            y=alt.Y(f"{col}:Q", title=metric, axis=alt.Axis(format=fmt)),
            tooltip=[alt.Tooltip("pickup_date:T"), alt.Tooltip(f"{col}:Q", format=fmt)],
        ).properties(height=320),
        use_container_width=True,
    )

with right:
    st.subheader("Revenue by payment type")
    pay = f.groupby("payment_type", as_index=False).agg(revenue=("revenue", "sum"))
    st.altair_chart(
        alt.Chart(pay).mark_arc(innerRadius=60).encode(
            theta="revenue:Q",
            color=alt.Color("payment_type:N", title=None),
            tooltip=["payment_type:N", alt.Tooltip("revenue:Q", format="$,.0f")],
        ).properties(height=320),
        use_container_width=True,
    )

# ---------------------------------------------------------------- row 2
st.subheader("When is demand highest?")
heat = f.groupby(["day_of_week", "hour_of_day"], as_index=False).agg(
    trips=("trips", "sum")
)
heat["weekday"] = heat.day_of_week.map(dict(enumerate(WEEKDAYS)))
st.altair_chart(
    alt.Chart(heat).mark_rect().encode(
        x=alt.X("hour_of_day:O", title="Hour of day"),
        y=alt.Y("weekday:N", sort=WEEKDAYS, title=None),
        color=alt.Color("trips:Q", scale=alt.Scale(scheme="oranges"), title="Trips"),
        tooltip=["weekday:N", "hour_of_day:O", alt.Tooltip("trips:Q", format=",.0f")],
    ).properties(height=260),
    use_container_width=True,
)

# ---------------------------------------------------------------- row 3
st.subheader("Top pickup zones")
n_zones = st.slider("How many zones", 5, 25, 10)
top = (
    zf.groupby(["zone", "borough"], as_index=False)
    .agg(pickups=("pickups", "sum"), revenue=("revenue", "sum"))
    .nlargest(n_zones, "pickups")
)
st.altair_chart(
    alt.Chart(top).mark_bar().encode(
        x=alt.X("pickups:Q", title="Pickups"),
        y=alt.Y("zone:N", sort="-x", title=None),
        color=alt.Color("borough:N", title="Borough"),
        tooltip=["zone:N", "borough:N",
                 alt.Tooltip("pickups:Q", format=",.0f"),
                 alt.Tooltip("revenue:Q", format="$,.0f")],
    ).properties(height=30 * n_zones),
    use_container_width=True,
)
st.caption("Zone ranking respects the date and borough filters "
           "(payment/hour filters apply to the sections above).")