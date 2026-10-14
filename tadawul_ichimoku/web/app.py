"""Flask web application: Tadawul scraper + Ichimoku analysis dashboard.

Run with:  python -m tadawul_ichimoku serve   (then open http://127.0.0.1:5000)
"""

from __future__ import annotations

import io
import math
import threading
import time
from typing import Any

import pandas as pd
from flask import Flask, jsonify, render_template, request

from ..ichimoku import IchimokuParams, analyze, compute_ichimoku
from ..scraper import ScrapeError, TadawulScraper, normalise_ohlcv

MARKET_TTL = 60  # seconds
ANALYSIS_TTL = 600

# A few large, liquid names used as the scanner's default watchlist.
DEFAULT_WATCHLIST = ["2222", "1120", "2010", "7010", "1180", "1211", "2082", "1150", "2380", "4190"]


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key, ttl: float):
        with self._lock:
            hit = self._data.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        return None

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(float(v), 4)


def _series(s: pd.Series) -> list:
    return [_clean(v) for v in s.astype(float).tolist()]


def tk_crosses(ich: pd.DataFrame) -> list[dict]:
    """All Tenkan/Kijun crossovers in the historical part of the frame."""
    hist = ich[ich["close"].notna()].dropna(subset=["tenkan", "kijun"])
    diff = hist["tenkan"] - hist["kijun"]
    sign = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    sign = sign.replace(0, pd.NA).ffill().fillna(0)
    out = []
    for i in range(1, len(sign)):
        if sign.iloc[i] != sign.iloc[i - 1] and sign.iloc[i - 1] != 0:
            row = hist.iloc[i]
            out.append({
                "date": hist.index[i].strftime("%Y-%m-%d"),
                "type": "bullish" if sign.iloc[i] > 0 else "bearish",
                "price": _clean(row["kijun"]),
            })
    return out


def build_payload(symbol: str, df: pd.DataFrame, source: str, params: IchimokuParams, name: str | None = None) -> dict:
    ich = compute_ichimoku(df, params)
    rep = analyze(ich, params)
    hist = ich[ich["close"].notna()]
    change = None
    if len(hist) > 1:
        prev = float(hist["close"].iloc[-2])
        change = _clean((rep.close - prev) / prev * 100) if prev else None
    return {
        "symbol": symbol,
        "name": name,
        "source": source,
        "bars": int(len(df)),
        "params": params.__dict__,
        "report": {
            "date": rep.date.strftime("%Y-%m-%d"),
            "close": _clean(rep.close),
            "change_pct": change,
            "tenkan": _clean(rep.tenkan),
            "kijun": _clean(rep.kijun),
            "cloud_top": _clean(rep.cloud_top),
            "cloud_bottom": _clean(rep.cloud_bottom),
            "score": rep.score,
            "verdict": rep.verdict,
            "signals": [s.__dict__ for s in rep.signals],
            "high_52w": _clean(hist["high"].tail(250).max()),
            "low_52w": _clean(hist["low"].tail(250).min()),
        },
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in ich.index],
            "last_actual": rep.date.strftime("%Y-%m-%d"),
            **{c: _series(ich[c]) for c in ("open", "high", "low", "close", "volume",
                                             "tenkan", "kijun", "senkou_a", "senkou_b", "chikou")},
        },
        "crosses": tk_crosses(ich),
    }


def _params_from_request() -> IchimokuParams:
    def arg(name, default):
        try:
            v = int(request.values.get(name, default))
        except (TypeError, ValueError):
            return default
        return min(max(v, 2), 200)

    return IchimokuParams(arg("tenkan", 9), arg("kijun", 26), arg("senkou_b", 52), arg("displacement", 26))


def create_app(scraper: TadawulScraper | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    scraper = scraper or TadawulScraper(retries=2)
    lock = threading.Lock()
    cache = TTLCache()

    def market() -> pd.DataFrame:
        snap = cache.get("market", MARKET_TTL)
        if snap is not None:
            return snap
        err = cache.get("market_error", MARKET_TTL)
        if err is not None:  # don't hammer the site (or stall every request) while it is failing
            raise ScrapeError(err)
        try:
            with lock:
                snap = scraper.get_market_snapshot()
        except ScrapeError as e:
            cache.set("market_error", str(e))
            raise
        cache.set("market", snap)
        return snap

    def name_of(symbol: str) -> str | None:
        try:
            snap = market()
        except ScrapeError:
            return None
        if {"symbol", "name"} <= set(snap.columns):
            hit = snap.loc[snap["symbol"] == symbol, "name"]
            return str(hit.iloc[0]) if len(hit) else None
        return None

    def analyse_symbol(symbol: str, days: int, source: str, params: IchimokuParams) -> dict:
        key = (symbol, days, source, tuple(params.__dict__.values()))
        hit = cache.get(key, ANALYSIS_TTL)
        if hit is not None:
            return hit
        with lock:
            df, used = scraper.get_history(symbol, days=days, source=source)
        payload = build_payload(symbol, df, used, params, name_of(symbol))
        cache.set(key, payload)
        return payload

    def error(msg: str, status: int):
        return jsonify({"error": msg}), status

    @app.get("/")
    def index():
        return render_template("index.html", watchlist=",".join(DEFAULT_WATCHLIST))

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.get("/api/market")
    def api_market():
        try:
            snap = market()
        except ScrapeError as e:
            return error(str(e), 502)
        rows = snap.astype(object).where(snap.notna(), None).to_dict(orient="records")
        return jsonify({"count": len(rows), "rows": rows, "fetched": time.strftime("%Y-%m-%d %H:%M:%S")})

    @app.get("/api/analyze/<symbol>")
    def api_analyze(symbol: str):
        symbol = symbol.strip().upper()
        if not symbol.isalnum() or len(symbol) > 10:
            return error("invalid symbol", 400)
        source = request.args.get("source", "auto")
        if source not in ("auto", "tadawul", "yahoo"):
            return error("invalid source", 400)
        days = min(max(request.args.get("days", 400, type=int), 120), 3650)
        try:
            return jsonify(analyse_symbol(symbol, days, source, _params_from_request()))
        except ScrapeError as e:
            return error(str(e), 502)
        except ValueError as e:
            return error(str(e), 422)

    @app.post("/api/analyze-csv")
    def api_analyze_csv():
        f = request.files.get("file")
        if not f:
            return error("no file uploaded", 400)
        symbol = (request.form.get("symbol") or f.filename.rsplit(".", 1)[0] or "CSV")[:20]
        try:
            df = normalise_ohlcv(pd.read_csv(io.BytesIO(f.read())))
            return jsonify(build_payload(symbol, df, f"csv:{f.filename}", _params_from_request()))
        except (ScrapeError, ValueError, pd.errors.ParserError) as e:
            return error(f"could not analyse CSV: {e}", 422)

    @app.get("/api/scan")
    def api_scan():
        raw = request.args.get("symbols") or ",".join(DEFAULT_WATCHLIST)
        symbols = [s.strip().upper() for s in raw.replace(" ", ",").split(",") if s.strip().isalnum()][:30]
        source = request.args.get("source", "auto")
        if source not in ("auto", "tadawul", "yahoo"):
            return error("invalid source", 400)
        params = _params_from_request()
        results = []
        for sym in symbols:
            try:
                p = analyse_symbol(sym, 400, source, params)
                r = p["report"]
                results.append({
                    "symbol": sym, "name": p["name"], "close": r["close"], "change_pct": r["change_pct"],
                    "score": r["score"], "verdict": r["verdict"], "date": r["date"],
                    "signals": {s["name"]: s["score"] for s in r["signals"]},
                    "spark": [v for v in p["series"]["close"] if v is not None][-60:],
                })
            except (ScrapeError, ValueError) as e:
                msg = " | ".join(line.strip() for line in str(e).splitlines() if line.strip())
                results.append({"symbol": sym, "error": msg[:240]})
        return jsonify({"results": results})

    return app


def run(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    create_app().run(host=host, port=port, debug=debug, threaded=True)
