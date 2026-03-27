import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone


def llm_categorize_bank_desc(text: str) -> str:
    mapping = {
        "fee": "GATEWAY_FEES",
        "refund": "REFUND",
        "settlement": "SETTLEMENT",
        "chargeback": "CHARGEBACK",
    }
    lowered = (text or "").lower()
    for keyword, code in mapping.items():
        if keyword in lowered:
            return code
    return "UNMAPPED"


def generate_mock_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n_rows = 100
    base_start = datetime(2026, 6, 28, 0, 0, 0, tzinfo=timezone.utc)
    cutoff_utc = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

    internal_df = pd.DataFrame({
        "internal_tx_id": [f"TXN_{1000 + i}" for i in range(n_rows)],
        "order_amount": np.round(np.random.uniform(10, 500, n_rows), 2),
        "created_at_utc": [base_start + timedelta(hours=i) for i in range(n_rows)],
        "status": "SUCCESS",
    })

    internal_df = pd.concat([internal_df, internal_df.iloc[10:11]], ignore_index=True)

    gateway_df = internal_df.drop_duplicates(subset=["internal_tx_id"]).copy()
    gateway_df["processed_at_utc"] = pd.to_datetime(gateway_df["created_at_utc"]) + timedelta(hours=1)
    gateway_df["fee_amount"] = np.round((gateway_df["order_amount"] * 0.029) + 0.30, 2)
    gateway_df["net_amount"] = gateway_df["order_amount"] - gateway_df["fee_amount"]

    orphan = pd.DataFrame({
        "internal_tx_id": ["TXN_99999"],
        "order_amount": [-100.0],
        "processed_at_utc": [cutoff_utc - timedelta(hours=5)],
        "fee_amount": [0.0],
        "net_amount": [-100.0],
    })
    gateway_df = pd.concat([gateway_df, orphan], ignore_index=True)

    gateway_df["processed_at_utc"] = pd.to_datetime(gateway_df["processed_at_utc"])
    gateway_df["batch_date_utc"] = gateway_df["processed_at_utc"].dt.date

    bank_df = (
        gateway_df.groupby("batch_date_utc")
        .agg({"net_amount": "sum", "internal_tx_id": "count"})
        .reset_index()
        .rename(columns={"net_amount": "credit_amount", "internal_tx_id": "tx_count"})
    )

    bank_df["cleared_at_utc"] = pd.to_datetime(bank_df["batch_date_utc"]) + timedelta(days=1)

    return internal_df, gateway_df, bank_df


def _ensure_utc(series: pd.Series) -> pd.Series:
    dt_series = pd.to_datetime(series, errors="coerce")
    if dt_series.dt.tz is None:
        return dt_series.dt.tz_localize("UTC")
    return dt_series.dt.tz_convert("UTC")


def run_reconciliation(
    internal: pd.DataFrame, gateway: pd.DataFrame, bank: pd.DataFrame
) -> dict:
    internal = internal.copy()
    gateway = gateway.copy()
    bank = bank.copy()

    internal["created_at_utc"] = _ensure_utc(internal["created_at_utc"])
    gateway["processed_at_utc"] = _ensure_utc(gateway["processed_at_utc"])
    bank["cleared_at_utc"] = _ensure_utc(bank["cleared_at_utc"])
    bank["batch_date_utc"] = _ensure_utc(bank["batch_date_utc"])

    june_cutoff = pd.Timestamp("2026-07-01", tz="UTC")

    gateway_scoped = gateway[gateway["processed_at_utc"] < june_cutoff]
    scoped_ids = set(gateway_scoped["internal_tx_id"])
    internal_scoped = internal[internal["internal_tx_id"].isin(scoped_ids)]

    dup_mask = internal_scoped.duplicated(subset=["internal_tx_id"], keep="first")
    duplicate_entries = internal_scoped[dup_mask]
    total_duplicate_val = duplicate_entries["order_amount"].sum()

    orphans = gateway_scoped[~gateway_scoped["internal_tx_id"].isin(internal["internal_tx_id"])]
    total_orphan_val = orphans["net_amount"].sum()

    june_lags = bank[(bank["cleared_at_utc"] >= june_cutoff) & (bank["batch_date_utc"] < june_cutoff)]
    total_lag_val = june_lags["credit_amount"].sum()

    internal_unique = internal_scoped.drop_duplicates(subset=["internal_tx_id"])
    comparison = pd.merge(internal_unique, gateway_scoped, on="internal_tx_id", how="inner")

    comparison["expected_fee"] = np.round((comparison["order_amount_x"] * 0.029) + 0.30, 2)
    comparison["rounding_diff"] = comparison["fee_amount"] - comparison["expected_fee"]
    total_rounding_variance = comparison["rounding_diff"].sum()
    total_fees_paid = comparison["fee_amount"].sum()

    expected_revenue = internal_scoped["order_amount"].sum()
    gateway_net_processed = gateway_scoped["net_amount"].sum()
    actual_bank_june = bank[bank["cleared_at_utc"] < june_cutoff]["credit_amount"].sum()

    summary = {
        "expected_revenue": float(expected_revenue),
        "gateway_net_processed": float(gateway_net_processed),
        "actual_bank_deposits": float(actual_bank_june),
        "total_lag": float(total_lag_val),
        "orphans": float(total_orphan_val),
        "rounding_variance": float(total_rounding_variance),
        "duplicate_values": float(total_duplicate_val),
        "gateway_fees": float(total_fees_paid),
    }

    return {
        "summary": summary,
        "duplicate_entries": duplicate_entries,
        "orphans": orphans,
        "june_lags": june_lags,
        "comparison": comparison,
    }