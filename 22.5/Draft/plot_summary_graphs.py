#!/usr/bin/env python3

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

PREFERRED_COLUMNS = [
    "rx_mbps_avg",
    "tx_mbps_avg",
    "qdisc_1_backlog_max",
    "qdisc_1_overlimits_sum",
]

EXCLUDED_COLUMNS = {
    "window_start",
    "window_end",
    "sample_count",
    "time_from_zero_min",
    "time_from_zero_max",
    "timestamp_min",
    "timestamp_max",
}


def choose_plot_columns(df, requested_columns):
    """Select which numeric summary columns to plot."""
    numeric_columns = [
        column for column in df.columns
        if column not in EXCLUDED_COLUMNS and pd.api.types.is_numeric_dtype(df[column])
    ]

    if requested_columns:
        missing = [column for column in requested_columns if column not in df.columns]
        if missing:
            raise SystemExit(f"Columns not found in summary CSV: {', '.join(missing)}")
        return requested_columns

    selected = [column for column in PREFERRED_COLUMNS if column in numeric_columns]
    if selected:
        return selected

    return numeric_columns[:4]


def default_output_path(summary_csv):
    summary_path = Path(summary_csv)
    return summary_path.parent / f"{summary_path.stem}_graphs.png"


def plot_summary(summary_csv, output_png, columns=None, title=None):
    df = pd.read_csv(summary_csv)
    if df.empty:
        raise SystemExit(f"Summary CSV is empty: {summary_csv}")
    if "window_start" not in df.columns:
        raise SystemExit("Summary CSV must contain a 'window_start' column")

    plot_columns = choose_plot_columns(df, columns)
    if not plot_columns:
        raise SystemExit("No numeric columns available to plot")

    x_values = df["window_start"]
    rows = len(plot_columns)
    fig, axes = plt.subplots(rows, 1, figsize=(12, max(3.2 * rows, 4)), squeeze=False)
    axes_flat = axes.flatten()

    figure_title = title or f"Summary Metrics per Window: {Path(summary_csv).name}"
    fig.suptitle(figure_title, fontsize=14)

    for axis, column in zip(axes_flat, plot_columns):
        axis.plot(x_values, df[column], marker="o", linewidth=1.8, color="#1f4e79")
        axis.set_title(column)
        axis.set_xlabel("window_start (s)")
        axis.set_ylabel(column)
        axis.grid(True, alpha=0.3)

    for axis in axes_flat[len(plot_columns):]:
        axis.axis("off")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return plot_columns


def main():
    parser = argparse.ArgumentParser(description="Plot metrics from a 5-second summary CSV.")
    parser.add_argument("summary_csv", help="Path to the summary CSV generated from experiment logs")
    parser.add_argument("--output-png", help="Output PNG file path")
    parser.add_argument("--columns", nargs="+", help="Specific summary columns to plot")
    parser.add_argument("--title", help="Optional chart title")
    args = parser.parse_args()

    output_png = Path(args.output_png) if args.output_png else default_output_path(args.summary_csv)
    plotted_columns = plot_summary(
        summary_csv=args.summary_csv,
        output_png=output_png,
        columns=args.columns,
        title=args.title,
    )

    print(f"Wrote graph: {output_png}")
    print(f"Plotted columns: {', '.join(plotted_columns)}")


if __name__ == "__main__":
    main()
