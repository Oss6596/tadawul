import numpy as np
import pandas as pd
import pytest

from tadawul_ichimoku.cli import main
from tadawul_ichimoku.ichimoku import IchimokuParams, analyze, compute_ichimoku
from tadawul_ichimoku.scraper import TadawulScraper, normalise_ohlcv


def make_prices(n=200, trend=0.2, seed=0):
    """Synthetic test series (only for unit tests)."""
    rng = np.random.default_rng(seed)
    close = 30 + np.cumsum(trend + rng.normal(0, 0.3, n))
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1000}, index=idx
    )


def test_lines_match_hand_calculation():
    df = make_prices()
    p = IchimokuParams()
    ich = compute_ichimoku(df, p)
    i = 120
    day = df.index[i]
    w9 = df.iloc[i - 8 : i + 1]
    w26 = df.iloc[i - 25 : i + 1]
    assert ich.loc[day, "tenkan"] == pytest.approx((w9.high.max() + w9.low.min()) / 2)
    assert ich.loc[day, "kijun"] == pytest.approx((w26.high.max() + w26.low.min()) / 2)
    # Senkou A at day i equals (tenkan+kijun)/2 of day i-26
    src = df.index[i - 26]
    assert ich.loc[day, "senkou_a"] == pytest.approx((ich.loc[src, "tenkan"] + ich.loc[src, "kijun"]) / 2)
    w52 = df.iloc[i - 26 - 51 : i - 26 + 1]
    assert ich.loc[day, "senkou_b"] == pytest.approx((w52.high.max() + w52.low.min()) / 2)
    # Chikou at day i is the close 26 bars later
    assert ich.loc[day, "chikou"] == pytest.approx(df.close.iloc[i + 26])
    # Cloud is projected 26 business days past the last bar
    assert len(ich) == len(df) + 26 and ich["senkou_a"].iloc[-1] == ich["senkou_a"].iloc[-1]


def test_uptrend_is_bullish_and_downtrend_bearish():
    up = analyze(compute_ichimoku(make_prices(trend=0.3)))
    down = analyze(compute_ichimoku(make_prices(trend=-0.3)))
    assert up.score == 5 and up.verdict == "STRONG BULLISH"
    assert down.score == -5 and down.verdict == "STRONG BEARISH"


def test_too_little_data_raises():
    with pytest.raises(ValueError):
        analyze(compute_ichimoku(make_prices(n=60)))


def test_normalise_tadawul_json_fields():
    raw = pd.DataFrame(
        [
            {"transactionDate": "2026-10-13", "todaysOpen": "27.10", "highPrice": "27.40",
             "lowPrice": "26.95", "lastTradePrice": "27.30", "volumeTraded": "12,345,678"},
            {"transactionDate": "2026-10-12", "todaysOpen": "27.00", "highPrice": "27.20",
             "lowPrice": "26.80", "lastTradePrice": "27.05", "volumeTraded": "9,000,000"},
        ]
    )
    df = normalise_ohlcv(raw)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing
    assert df["volume"].iloc[-1] == 12345678 and df["close"].iloc[-1] == 27.30


class FakeResp:
    def __init__(self, text="", js=None, status=200):
        self.text, self._js, self.status_code = text, js, status

    def json(self):
        if self._js is None:
            raise ValueError
        return self._js


class FakeSession:
    headers: dict = {}

    def __init__(self):
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        if url.endswith("TickerServlet"):
            return FakeResp(js={"stockData": [{"pk_rf_company": "2222", "companyShortNameEn": "ARAMCO",
                                               "lastTradePrice": 27.3, "changePercent": 0.9}]})
        if "company-profile-main/" in url and method == "GET":
            return FakeResp(text='<div data-url="x"></div><script>var u = "/wps/portal/saudiexchange/hidden/'
                                 'company-profile-main/!ut/p/z1/abc/p0/IZ7_X=CZ6_Y=NJgetStockHistoricalData=/";</script>')
        if "getStockHistoricalData" in url and method == "POST":
            return FakeResp(js={"data": [{"transactionDate": "2026-10-13", "todaysOpen": 27, "highPrice": 27.5,
                                          "lowPrice": 26.9, "lastTradePrice": 27.3, "volumeTraded": 100}]})
        return FakeResp(text="<html></html>")


def test_scraper_flow_with_mocked_site():
    s = TadawulScraper(session=FakeSession(), retries=1)
    snap = s.get_market_snapshot()
    assert snap.iloc[0].to_dict() == {"symbol": "2222", "name": "ARAMCO", "price": 27.3, "change_pct": 0.9}
    df, src = s.get_history("2222", source="tadawul")
    assert src == "tadawul" and df["close"].iloc[0] == 27.3
    assert any(m == "POST" and "getStockHistoricalData" in u for m, u in s.session.calls)


def test_cli_with_csv(tmp_path, capsys):
    csv = tmp_path / "p.csv"
    make_prices().rename_axis("Date").reset_index().to_csv(csv, index=False)
    rc = main(["analyze", "TEST", "--csv", str(csv), "--plot", "--out", str(tmp_path / "out")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ichimoku analysis: TEST" in out and "Score:" in out
    assert (tmp_path / "out" / "TEST_ichimoku.png").stat().st_size > 10_000


# ---------------------------------------------------------------- web app
from tadawul_ichimoku.scraper import ScrapeError
from tadawul_ichimoku.web.app import create_app


class FakeScraper:
    def __init__(self, fail=False):
        self.fail = fail

    def get_market_snapshot(self):
        if self.fail:
            raise ScrapeError("blocked")
        return pd.DataFrame([{"symbol": "2222", "name": "ARAMCO", "price": 27.3, "change": 0.2, "change_pct": 0.74}])

    def get_history(self, symbol, days=400, source="auto"):
        if self.fail or symbol == "9999":
            raise ScrapeError("all sources failed")
        return make_prices(n=260, trend=0.1), "tadawul"


@pytest.fixture
def client():
    return create_app(FakeScraper()).test_client()


def test_web_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Tadawul Ichimoku" in r.data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/vendor/plotly.min.js").status_code == 200


def test_web_analyze_payload(client):
    d = client.get("/api/analyze/2222?tenkan=9&kijun=26").get_json()
    assert d["name"] == "ARAMCO" and d["source"] == "tadawul"
    assert d["report"]["verdict"] and len(d["report"]["signals"]) == 5
    s = d["series"]
    assert len(s["dates"]) == len(s["close"]) == 260 + 26
    assert s["close"][-1] is None and s["senkou_a"][-1] is not None  # projected cloud
    # projected dates fall on Saudi trading days (no Friday/Saturday)
    future = pd.to_datetime(s["dates"][260:])
    assert not any(future.dayofweek.isin([4, 5]))


def test_web_errors(client):
    assert client.get("/api/analyze/9999").status_code == 502
    assert client.get("/api/analyze/22$2").status_code in (400, 404)
    bad = create_app(FakeScraper(fail=True)).test_client()
    assert bad.get("/api/market").status_code == 502


def test_web_scan_and_csv(client, tmp_path):
    d = client.get("/api/scan?symbols=2222,9999").get_json()["results"]
    assert d[0]["symbol"] == "2222" and "score" in d[0] and "error" in d[1]
    import io
    buf = io.BytesIO()
    make_prices().rename_axis("Date").reset_index().to_csv(buf, index=False)
    buf.seek(0)
    r = client.post("/api/analyze-csv", data={"file": (buf, "demo.csv"), "symbol": "DEMO"},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["symbol"] == "DEMO"
