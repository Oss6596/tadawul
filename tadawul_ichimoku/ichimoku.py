"""Ichimoku Kinko Hyo indicator and a simple rule-based signal summary.

Components (default periods 9 / 26 / 52, displacement 26):

* Tenkan-sen  (conversion line) = midpoint of the 9-period high/low
* Kijun-sen   (base line)       = midpoint of the 26-period high/low
* Senkou A    (leading span A)  = (Tenkan + Kijun) / 2, plotted 26 periods ahead
* Senkou B    (leading span B)  = midpoint of the 52-period high/low, plotted 26 ahead
* Chikou      (lagging span)    = close, plotted 26 periods behind

The cloud (kumo) is the area between Senkou A and Senkou B.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class IchimokuParams:
    tenkan: int = 9
    kijun: int = 26
    senkou_b: int = 52
    displacement: int = 26


# Tadawul trades Sunday-Thursday; used to date the projected cloud.
SAUDI_WEEKMASK = "Sun Mon Tue Wed Thu"


def _midpoint(high: pd.Series, low: pd.Series, window: int) -> pd.Series:
    return (high.rolling(window).max() + low.rolling(window).min()) / 2


def compute_ichimoku(df: pd.DataFrame, params: IchimokuParams = IchimokuParams()) -> pd.DataFrame:
    """Return a copy of ``df`` (needs high/low/close columns, date index) with Ichimoku columns.

    The frame is extended by ``displacement`` future Saudi trading days (Sun-Thu) so the
    forward-shifted cloud can be plotted. Columns added:

    tenkan, kijun   - unshifted lines
    senkou_a, senkou_b - leading spans already shifted forward (as plotted)
    chikou          - close shifted backward (as plotted)
    cloud_a, cloud_b - the cloud value *at each row's own date*, i.e. the spans
                       that were computed ``displacement`` bars earlier. This is
                       what price is compared against "now".
    """
    missing = {"high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    p = params
    out = df.sort_index().copy()

    future_idx = pd.bdate_range(
        out.index[-1] + pd.Timedelta(days=1), periods=p.displacement, freq="C", weekmask=SAUDI_WEEKMASK
    )
    out = out.reindex(out.index.append(future_idx))

    tenkan = _midpoint(out["high"], out["low"], p.tenkan)
    kijun = _midpoint(out["high"], out["low"], p.kijun)
    span_a_raw = (tenkan + kijun) / 2
    span_b_raw = _midpoint(out["high"], out["low"], p.senkou_b)

    out["tenkan"] = tenkan
    out["kijun"] = kijun
    out["senkou_a"] = span_a_raw.shift(p.displacement)
    out["senkou_b"] = span_b_raw.shift(p.displacement)
    out["chikou"] = out["close"].shift(-p.displacement)
    # Cloud as it stands at each date (same as the shifted spans).
    out["cloud_a"] = out["senkou_a"]
    out["cloud_b"] = out["senkou_b"]
    return out


@dataclass
class Signal:
    name: str
    value: str
    score: int  # +1 bullish, -1 bearish, 0 neutral
    detail: str = ""


@dataclass
class IchimokuReport:
    date: pd.Timestamp
    close: float
    tenkan: float
    kijun: float
    cloud_top: float
    cloud_bottom: float
    signals: list[Signal] = field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(s.score for s in self.signals)

    @property
    def verdict(self) -> str:
        s = self.score
        if s >= 3:
            return "STRONG BULLISH"
        if s >= 1:
            return "BULLISH"
        if s <= -3:
            return "STRONG BEARISH"
        if s <= -1:
            return "BEARISH"
        return "NEUTRAL"


def analyze(ich: pd.DataFrame, params: IchimokuParams = IchimokuParams(), cross_lookback: int = 5) -> IchimokuReport:
    """Evaluate the classic Ichimoku rules on the last actual trading day."""
    hist = ich[ich["close"].notna()]
    if len(hist) < params.senkou_b + params.displacement:
        raise ValueError(
            f"need at least {params.senkou_b + params.displacement} bars for a full Ichimoku, got {len(hist)}"
        )
    last = hist.iloc[-1]
    date = hist.index[-1]
    close = float(last["close"])
    top = float(max(last["cloud_a"], last["cloud_b"]))
    bottom = float(min(last["cloud_a"], last["cloud_b"]))
    signals: list[Signal] = []

    # 1. Price vs cloud
    if close > top:
        signals.append(Signal("Price vs Cloud", "above", 1, f"close {close:.2f} > cloud top {top:.2f}"))
    elif close < bottom:
        signals.append(Signal("Price vs Cloud", "below", -1, f"close {close:.2f} < cloud bottom {bottom:.2f}"))
    else:
        signals.append(Signal("Price vs Cloud", "inside", 0, f"close {close:.2f} within {bottom:.2f}-{top:.2f}"))

    # 2. Tenkan vs Kijun (and recent cross)
    tk = hist["tenkan"] - hist["kijun"]
    recent = tk.iloc[-(cross_lookback + 1):]
    sign = recent.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    crossed = (sign.diff().fillna(0) != 0) & (sign != 0)
    cross_note = ""
    if crossed.iloc[1:].any():
        cross_day = crossed.iloc[1:][crossed.iloc[1:]].index[-1]
        kind = "bullish" if sign.loc[cross_day] > 0 else "bearish"
        cross_note = f"; {kind} TK cross on {cross_day.date()}"
    t, k = float(last["tenkan"]), float(last["kijun"])
    if t > k:
        signals.append(Signal("Tenkan vs Kijun", "tenkan above", 1, f"{t:.2f} > {k:.2f}{cross_note}"))
    elif t < k:
        signals.append(Signal("Tenkan vs Kijun", "tenkan below", -1, f"{t:.2f} < {k:.2f}{cross_note}"))
    else:
        signals.append(Signal("Tenkan vs Kijun", "equal", 0, f"{t:.2f} = {k:.2f}{cross_note}"))

    # 3. Price vs Kijun (trend / momentum)
    if close > k:
        signals.append(Signal("Price vs Kijun", "above", 1, f"close above base line {k:.2f}"))
    elif close < k:
        signals.append(Signal("Price vs Kijun", "below", -1, f"close below base line {k:.2f}"))
    else:
        signals.append(Signal("Price vs Kijun", "on", 0, ""))

    # 4. Future cloud colour (the span projected 26 bars ahead)
    fut = ich.iloc[-1]
    fa, fb = float(fut["senkou_a"]), float(fut["senkou_b"])
    if fa > fb:
        signals.append(Signal("Future Cloud", "green", 1, f"Span A {fa:.2f} > Span B {fb:.2f}"))
    elif fa < fb:
        signals.append(Signal("Future Cloud", "red", -1, f"Span A {fa:.2f} < Span B {fb:.2f}"))
    else:
        signals.append(Signal("Future Cloud", "flat", 0, ""))

    # 5. Chikou: today's close vs price 26 bars ago
    past_close = float(hist["close"].iloc[-(params.displacement + 1)])
    if close > past_close:
        signals.append(Signal("Chikou Span", "above past price", 1, f"{close:.2f} vs {past_close:.2f} {params.displacement} bars ago"))
    elif close < past_close:
        signals.append(Signal("Chikou Span", "below past price", -1, f"{close:.2f} vs {past_close:.2f} {params.displacement} bars ago"))
    else:
        signals.append(Signal("Chikou Span", "equal", 0, ""))

    return IchimokuReport(date, close, t, k, top, bottom, signals)


def format_report(symbol: str, name: str | None, rep: IchimokuReport) -> str:
    title = f"{symbol}" + (f" - {name}" if name else "")
    lines = [
        "=" * 64,
        f" Ichimoku analysis: {title}",
        f" As of {rep.date.date()}   Close: {rep.close:.2f} SAR",
        "=" * 64,
        f" Tenkan-sen: {rep.tenkan:9.2f}    Kijun-sen: {rep.kijun:9.2f}",
        f" Cloud now : {rep.cloud_bottom:9.2f} - {rep.cloud_top:.2f}",
        "-" * 64,
    ]
    marks = {1: "[+]", -1: "[-]", 0: "[ ]"}
    for s in rep.signals:
        lines.append(f" {marks[s.score]} {s.name:<16} {s.value:<18} {s.detail}")
    lines += ["-" * 64, f" Score: {rep.score:+d} / 5  ->  {rep.verdict}", "=" * 64]
    return "\n".join(lines)
