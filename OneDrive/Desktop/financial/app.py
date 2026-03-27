# This implementation uses synthetic random data and does not reconcile against immutable source-of-truth ledgers from real systems.
# It assumes clean shared identifiers across systems and does not handle production realities like partial captures, chargebacks, or asynchronous correction files.
# It also hard-codes a single UTC cutoff window and omits controls for schema drift, idempotent reruns, and operational alerting.

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from reconciliation_engine import generate_mock_data, run_reconciliation


def currency(value: float) -> str:
    return f"${value:,.2f}"


st.set_page_config(page_title="Payments Reconciliation Dashboard", layout="wide")
st.title("Payments Reconciliation Dashboard")

internal_df, gateway_df, bank_df = generate_mock_data()
results = run_reconciliation(internal_df, gateway_df, bank_df)

summary = results["summary"]
expected_revenue = summary["expected_revenue"]
gateway_net_processed = summary["gateway_net_processed"]
actual_bank_deposits = summary["actual_bank_deposits"]
gateway_fees = summary["gateway_fees"]
rounding_variance = summary["rounding_variance"]
timing_lag = summary["total_lag"]
orphans_val = summary["orphans"]
duplicate_values = summary["duplicate_values"]

reconciled_value = (
    expected_revenue
    - gateway_fees
    - rounding_variance
    - timing_lag
    + orphans_val
    - duplicate_values
)

unexplained_residual = round(
    expected_revenue
    - (
        actual_bank_deposits
        + gateway_fees
        + rounding_variance
        + timing_lag
        + duplicate_values
        - orphans_val
    ),
    2,
)
if abs(unexplained_residual) < 0.01:
    unexplained_residual = 0.0

st.header("Executive Summary")
kpi_cols = st.columns(4)
kpi_cols[0].metric("Internal Expected Revenue", currency(expected_revenue))
kpi_cols[1].metric("Gateway Net Processed", currency(gateway_net_processed))
kpi_cols[2].metric("Actual Bank Deposits", currency(actual_bank_deposits))
kpi_cols[3].metric("Unexplained Residual", currency(unexplained_residual))

st.header("The 3-Way Gap Breakdown")

waterfall_labels = [
    "Internal Expected Revenue",
    "Gateway Fees",
    "Rounding Variance",
    "Timing Lags",
    "Orphans",
    "Duplicates",
    "Actual Bank Deposits",
]

waterfall_measures = ["absolute", "relative", "relative", "relative", "relative", "relative", "total"]
waterfall_values = [
    expected_revenue,
    -gateway_fees,
    -rounding_variance,
    -timing_lag,
    orphans_val,
    -duplicate_values,
    actual_bank_deposits,
]

fig = go.Figure(
    go.Waterfall(
        name="Reconciliation Bridge",
        orientation="v",
        measure=waterfall_measures,
        x=waterfall_labels,
        y=waterfall_values,
        text=[currency(v) for v in waterfall_values],
        textposition="outside",
    )
)
fig.update_layout(height=450, showlegend=False, margin=dict(l=20, r=20, t=20, b=20))
st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Bridge check: "
    f"Expected ({currency(expected_revenue)}) - Fees ({currency(gateway_fees)}) - Rounding ({currency(rounding_variance)}) "
    f"- Timing ({currency(timing_lag)}) + Orphans ({currency(orphans_val)}) - Duplicates ({currency(duplicate_values)}) "
    f"= {currency(reconciled_value)}"
)

st.header("Action Grid")
tab1, tab2, tab3 = st.tabs(["Duplicate Entries", "Orphans", "June Lags"])

with tab1:
    st.dataframe(results["duplicate_entries"], use_container_width=True)

with tab2:
    st.dataframe(results["orphans"], use_container_width=True)

with tab3:
    st.dataframe(results["june_lags"], use_container_width=True)

with st.expander("Fee and Precision Comparison"):
    st.dataframe(results["comparison"], use_container_width=True)