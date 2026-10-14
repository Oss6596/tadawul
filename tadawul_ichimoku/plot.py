"""Ichimoku chart rendering."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def plot_ichimoku(ich: pd.DataFrame, title: str, path: str, last_n: int = 180) -> str:
    """Save an Ichimoku chart of the last ``last_n`` trading days (+ projected cloud)."""
    hist_mask = ich["close"].notna()
    start = ich.index[hist_mask][-last_n] if hist_mask.sum() > last_n else ich.index[0]
    d = ich.loc[start:]
    a, b = d["senkou_a"], d["senkou_b"]

    fig, ax = plt.subplots(figsize=(13, 6.5))
    ax.fill_between(d.index, a, b, where=a >= b, color="#2e9e5b", alpha=0.22, interpolate=True, label="Kumo (bullish)")
    ax.fill_between(d.index, a, b, where=a < b, color="#d1495b", alpha=0.22, interpolate=True, label="Kumo (bearish)")
    ax.plot(d.index, a, color="#2e9e5b", lw=0.8, label="Senkou Span A")
    ax.plot(d.index, b, color="#d1495b", lw=0.8, label="Senkou Span B")
    ax.plot(d.index, d["close"], color="#222222", lw=1.6, label="Close")
    ax.plot(d.index, d["tenkan"], color="#1f77b4", lw=1.1, label="Tenkan-sen (9)")
    ax.plot(d.index, d["kijun"], color="#b5651d", lw=1.1, label="Kijun-sen (26)")
    ax.plot(d.index, d["chikou"], color="#8e44ad", lw=1.0, ls="--", label="Chikou Span")

    last_day = ich.index[hist_mask][-1]
    ax.axvline(last_day, color="grey", lw=0.8, ls=":")
    ax.set_title(title)
    ax.set_ylabel("Price (SAR)")
    ax.grid(alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
