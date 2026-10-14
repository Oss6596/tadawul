"""Build a self-contained, static demo of the web app (no server needed).

The demo runs on SYNTHETIC prices for invented "Demo" stocks, computed with the
real Ichimoku code, so the interface can be previewed anywhere. It is clearly
labelled as demo data on the page.

    python scripts/build_demo.py OUTPUT.html
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tadawul_ichimoku.ichimoku import SAUDI_WEEKMASK  # noqa: E402
from tadawul_ichimoku.web import app as webapp  # noqa: E402

PLOTLY_CDN = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"

# (symbol, name, start price, drift per day, volatility, regime-change day or None, drift after)
DEMO_STOCKS = [
    ("DEMOA", "Demo Energy", 28.0, 0.0009, 0.012, None, None),
    ("DEMOB", "Demo Bank", 82.0, -0.0004, 0.014, 230, 0.0030),
    ("DEMOC", "Demo Petrochem", 74.0, 0.0002, 0.016, 200, -0.0030),
    ("DEMOD", "Demo Telecom", 41.0, 0.0000, 0.011, None, None),
    ("DEMOE", "Demo Retail", 112.0, -0.0012, 0.017, None, None),
    ("DEMOF", "Demo Utilities", 96.0, 0.0015, 0.019, 260, -0.0010),
    ("DEMOG", "Demo Mining", 52.0, 0.0006, 0.020, None, None),
    ("DEMOH", "Demo Insurance", 18.5, -0.0006, 0.015, 240, 0.0020),
]
EXTRA_MARKET = ["Demo Cement", "Demo Foods", "Demo Logistics", "Demo REIT", "Demo Healthcare",
                "Demo Media", "Demo Steel", "Demo Agri", "Demo Transport", "Demo Software",
                "Demo Hotels", "Demo Chemicals"]


def synthetic_ohlcv(seed, start, drift, vol, change_at=None, drift2=None, n=320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-10-14", periods=n, freq="C", weekmask=SAUDI_WEEKMASK)
    closes, opens, highs, lows = [], [], [], []
    prev = start
    for i in range(n):
        mu = drift2 if (change_at is not None and i >= change_at) else drift
        o = prev * (1 + rng.normal(0, vol * 0.3))
        c = o * (1 + mu + rng.normal(0, vol))
        h = max(o, c) * (1 + abs(rng.normal(0, vol * 0.5)))
        lo = min(o, c) * (1 - abs(rng.normal(0, vol * 0.5)))
        opens.append(o); closes.append(c); highs.append(h); lows.append(lo)
        prev = c
    vol_ = (rng.lognormal(14, 0.45, n)).round()
    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vol_}, index=idx)
    return df.round(2)


class DemoScraper:
    def __init__(self):
        self.frames = {s: synthetic_ohlcv(i + 7, *spec[1:]) for i, (s, *spec) in enumerate(DEMO_STOCKS)}
        rows = []
        for sym, name, *_ in DEMO_STOCKS:
            df = self.frames[sym]
            c, p = df["close"].iloc[-1], df["close"].iloc[-2]
            rows.append({"symbol": sym, "name": name, "price": c, "change": round(c - p, 2),
                         "change_pct": round((c - p) / p * 100, 2)})
        rng = np.random.default_rng(99)
        for i, name in enumerate(EXTRA_MARKET):
            price = round(float(rng.uniform(12, 140)), 2)
            pct = round(float(rng.normal(0, 1.4)), 2)
            rows.append({"symbol": f"DEMO{i + 10}", "name": name, "price": price,
                         "change": round(price * pct / 100, 2), "change_pct": pct})
        self.market = pd.DataFrame(rows)

    def get_market_snapshot(self):
        return self.market

    def get_history(self, symbol, days=400, source="auto"):
        if symbol not in self.frames:
            raise webapp.ScrapeError(f"{symbol} is not in the demo data set")
        return self.frames[symbol], "demo (synthetic)"


SHIM = r"""
<script>
/* Demo mode: answer the app's API calls from bundled synthetic data. */
(() => {
  const DATA = __DATA__;
  const json = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body),
    { status, headers: { "Content-Type": "application/json" } }));
  const known = Object.keys(DATA.analyze).join(", ");
  window.TADAWUL_POPULAR = DATA.popular;
  window.TADAWUL_DEFAULT_SYMBOL = DATA.popular[0][0];
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, opts) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const p = url.pathname;
    if (p.endsWith("/api/market")) return json(DATA.market);
    let m = p.match(/\/api\/analyze\/([^/]+)$/);
    if (m) {
      const sym = decodeURIComponent(m[1]).toUpperCase();
      return DATA.analyze[sym] ? json(DATA.analyze[sym])
        : json({ error: `${sym} is not in this demo. Demo symbols: ${known}. Run the app locally to analyse real Tadawul stocks.` }, 404);
    }
    if (p.endsWith("/api/analyze-csv"))
      return json({ error: "CSV upload needs the Python server. Run: python -m tadawul_ichimoku serve" }, 422);
    if (p.endsWith("/api/scan")) {
      const syms = (url.searchParams.get("symbols") || "").toUpperCase().split(/[\s,]+/).filter(Boolean);
      return json({ results: syms.slice(0, 30).map(s => DATA.scan[s] || { symbol: s, error: "not in the demo data set" }) });
    }
    return realFetch(input, opts);
  };
})();
</script>
"""

BANNER = """<div class="demo-banner" role="note"><strong>Demo data.</strong> Every stock here is invented and every price is
synthetic. Run <code>python -m tadawul_ichimoku serve</code> to analyse real Saudi Exchange stocks.
In this demo, parameter changes and CSV upload are disabled.</div>"""

BANNER_CSS = """
.demo-banner { background: var(--surface-2); border-bottom: 1px solid var(--border); color: var(--ink-2); font-size: 13px;
  padding-block: 8px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  text-align: center; }
.demo-banner strong { color: var(--ink); }
.demo-banner code { font-size: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; }
"""


def build(out: Path) -> None:
    scraper = DemoScraper()
    webapp.DEFAULT_WATCHLIST = [s for s, *_ in DEMO_STOCKS]
    client = webapp.create_app(scraper).test_client()

    data = {
        "market": client.get("/api/market").get_json(),
        "analyze": {s: client.get(f"/api/analyze/{s}").get_json() for s, *_ in DEMO_STOCKS},
        "popular": [[s, n] for s, n, *_ in DEMO_STOCKS],
    }
    data["market"]["fetched"] = "demo data"
    scan = client.get("/api/scan?symbols=" + ",".join(data["analyze"])).get_json()["results"]
    data["scan"] = {r["symbol"]: r for r in scan}

    html = client.get("/").get_data(as_text=True)
    static = ROOT / "tadawul_ichimoku" / "web" / "static"
    css = (static / "style.css").read_text() + BANNER_CSS
    js = (static / "app.js").read_text()

    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    title = re.search(r"<title>.*?</title>", head).group(0)
    icon = re.search(r'<link rel="icon" href="[^"]*">', head).group(0)

    page = "\n".join([
        title,
        '<meta name="claude:viewport-fit-sides" content="cover">',
        icon,
        f"<style>\n{css}\n</style>",
        BANNER,
        body,
        f'<script src="{PLOTLY_CDN}"></script>',
        SHIM.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
        f"<script>\n{js}\n</script>",
    ])
    out.write_text(page)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    for s, p in data["analyze"].items():
        print(f"  {s:6} {p['report']['close']:>8.2f}  {p['report']['score']:+d}  {p['report']['verdict']}")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "demo.html"))
