#!/usr/bin/env python3

import argparse
from pathlib import Path

import pandas as pd

BASE_COLUMNS = [
    "timestamp",
    "rx_packets",
    "rx_bytes",
    "tx_packets",
    "tx_bytes",
]

DELTA_SUFFIXES = ("rx_packets", "rx_bytes", "tx_packets", "tx_bytes", "bytes", "packets", "drops", "overlimits")


def parse_log_line(line):
    """Parse one collate_stats.py output line into a flat dict."""
    parts = line.strip().split()
    if len(parts) < 5:
        return None

    row = {
        "timestamp": float(parts[0]),
        "rx_packets": int(parts[1]),
        "rx_bytes": int(parts[2]),
        "tx_packets": int(parts[3]),
        "tx_bytes": int(parts[4]),
    }

    qdisc_parts = parts[5:]
    qdisc_count = len(qdisc_parts) // 6
    for index in range(qdisc_count):
        offset = index * 6
        prefix = f"qdisc_{index + 1}"
        row[f"{prefix}_type"] = qdisc_parts[offset]
        row[f"{prefix}_backlog"] = int(qdisc_parts[offset + 1])
        row[f"{prefix}_bytes"] = int(qdisc_parts[offset + 2])
        row[f"{prefix}_packets"] = int(qdisc_parts[offset + 3])
        row[f"{prefix}_drops"] = int(qdisc_parts[offset + 4])
        row[f"{prefix}_overlimits"] = int(qdisc_parts[offset + 5])

    return row


def load_log_dataframe(input_path):
    """Load a raw stats log into a DataFrame."""
    rows = []
    with open(input_path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("No qdisc info available"):
                continue
            parsed = parse_log_line(stripped)
            if parsed is not None:
                rows.append(parsed)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    first_timestamp = df["timestamp"].iloc[0]
    df.insert(0, "time_from_zero", df["timestamp"] - first_timestamp)
    return df


def build_summary_dataframe(df, window_seconds):
    """Build a compact 5-second summary focused on congestion indicators."""
    summary_input = df.copy()
    summary_input["window_start"] = (summary_input["time_from_zero"] // window_seconds) * window_seconds
    summary_input["window_end"] = summary_input["window_start"] + window_seconds

    aggregations = {
        "time_from_zero": ["min", "max"],
        "rx_bytes": "sum",
        "tx_bytes": "sum",
        "rx_packets": "sum",
        "tx_packets": "sum",
    }

    if "qdisc_1_backlog" in summary_input.columns:
        aggregations["qdisc_1_backlog"] = ["mean", "max"]
    if "qdisc_1_drops" in summary_input.columns:
        aggregations["qdisc_1_drops"] = "sum"
    if "qdisc_1_overlimits" in summary_input.columns:
        aggregations["qdisc_1_overlimits"] = "sum"

    summary = summary_input.groupby("window_start", as_index=False).agg(aggregations)
    summary.columns = flatten_columns(summary.columns)
    summary["window_end"] = summary["window_start"] + window_seconds
    summary["sample_count"] = summary_input.groupby("window_start").size().values
    summary["rx_mbps_avg"] = summary["rx_bytes_sum"] * 8 / window_seconds / 1_000_000
    summary["tx_mbps_avg"] = summary["tx_bytes_sum"] * 8 / window_seconds / 1_000_000

    ordered_columns = [
        "window_start",
        "window_end",
        "sample_count",
        "time_from_zero_min",
        "time_from_zero_max",
        "rx_mbps_avg",
        "tx_mbps_avg",
        "rx_bytes_sum",
        "tx_bytes_sum",
        "rx_packets_sum",
        "tx_packets_sum",
    ]

    optional_columns = [
        "qdisc_1_backlog_mean",
        "qdisc_1_backlog_max",
        "qdisc_1_drops_sum",
        "qdisc_1_overlimits_sum",
    ]

    existing_optional = [column for column in optional_columns if column in summary.columns]
    return summary[ordered_columns + existing_optional]


def flatten_columns(columns):
    """Flatten pandas MultiIndex columns into simple strings."""
    flattened = []
    for column in columns:
        if isinstance(column, tuple):
            parts = [str(part) for part in column if part]
            flattened.append("_".join(parts))
        else:
            flattened.append(str(column))
    return flattened


def default_output_paths(input_path):
    input_file = Path(input_path)
    parent = input_file.parent
    stem = input_file.stem
    return (
        parent / f"{stem}_full.csv",
        parent / f"{stem}_summary_5s.csv",
    )


def main():
    parser = argparse.ArgumentParser(description="Convert a raw experiment log into detailed and 5-second summary CSV files.")
    parser.add_argument("input_log", help="Path to the raw .log file produced by the experiment")
    parser.add_argument("--window", type=int, default=5, help="Summary window size in seconds")
    parser.add_argument("--output-csv", help="Output path for the detailed CSV")
    parser.add_argument("--summary-csv", help="Output path for the summary CSV")
    args = parser.parse_args()

    full_output, summary_output = default_output_paths(args.input_log)
    if args.output_csv:
        full_output = Path(args.output_csv)
    if args.summary_csv:
        summary_output = Path(args.summary_csv)

    df = load_log_dataframe(args.input_log)
    if df.empty:
        raise SystemExit(f"No valid data rows found in {args.input_log}")

    summary_df = build_summary_dataframe(df, args.window)

    df.to_csv(full_output, index=False)
    summary_df.to_csv(summary_output, index=False)

    print(f"Wrote detailed CSV: {full_output}")
    print(f"Wrote summary CSV: {summary_output}")


if __name__ == "__main__":
    main()
