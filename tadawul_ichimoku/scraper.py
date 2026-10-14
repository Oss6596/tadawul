"""Scrape prices from the Saudi Exchange (Tadawul) website.

Two sources on www.saudiexchange.sa are used:

1. ``TickerServlet`` - a JSON feed behind the scrolling ticker on the home page,
   giving the latest price of every listed company. Used for ``list`` / quotes.
2. The company profile page's *Historical Data* tab. Its data comes from a
   WebSphere portlet "resource URL" (``.../!ut/p/z1/...``) that changes per
   session, so the page is downloaded first and the URL is discovered in the
   HTML, then queried for daily OHLCV rows (DataTables-style JSON).

The site is behind a WAF and its markup changes from time to time; field
names are therefore matched through alias tables, and a Yahoo Finance
fallback (``<symbol>.SR``) is available with ``source="yahoo"``/``"auto"``.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.saudiexchange.sa"
HOME_URL = f"{BASE_URL}/wps/portal/saudiexchange/home"
TICKER_URL = f"{BASE_URL}/tadawul.eportal.theme.helper/TickerServlet"
COMPANY_URL = f"{BASE_URL}/wps/portal/saudiexchange/hidden/company-profile-main/"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.SR"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
}

# Possible JSON keys for each normalised column (Tadawul has used several).
FIELD_ALIASES = {
    "date": ["transactionDate", "tradingDate", "date", "tradeDate", "Date"],
    "open": ["todaysOpen", "openPrice", "open", "Open"],
    "high": ["highPrice", "todaysHigh", "high", "High"],
    "low": ["lowPrice", "todaysLow", "low", "Low"],
    "close": ["lastTradePrice", "closePrice", "close", "Close", "lastPrice"],
    "volume": ["volumeTraded", "volume", "totalVolume", "Volume"],
}

# Regex used to find the historical-data resource URL inside the profile page.
_HIST_URL_RE = re.compile(
    r"""["'](?P<url>/wps/portal/saudiexchange/[^"']*?(?:[Hh]istorical|getStockHistory|stockHistory)[^"']*)["']"""
)


class ScrapeError(RuntimeError):
    pass


class TadawulScraper:
    def __init__(self, timeout: float = 30.0, retries: int = 3, session: requests.Session | None = None):
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self._warmed_up = False

    # ------------------------------------------------------------------ http
    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.session.request(method, url, timeout=self.timeout, **kw)
                if r.status_code == 200:
                    return r
                last_exc = ScrapeError(f"HTTP {r.status_code} from {url}")
            except requests.RequestException as e:
                last_exc = e
            time.sleep(1.5 * (attempt + 1))
        raise ScrapeError(f"request failed: {url}: {last_exc}")

    def _warm_up(self) -> None:
        """Visit the home page once so the WAF/session cookies are set."""
        if not self._warmed_up:
            try:
                self._request("GET", HOME_URL)
            except ScrapeError:
                pass  # not fatal; the next call reports the real error
            self._warmed_up = True

    # ---------------------------------------------------------------- quotes
    def get_market_snapshot(self) -> pd.DataFrame:
        """Latest price of every listed company from the ticker feed."""
        self._warm_up()
        r = self._request("GET", TICKER_URL, headers={"Referer": HOME_URL, "Accept": "application/json"})
        try:
            payload = r.json()
        except ValueError as e:
            raise ScrapeError("ticker feed did not return JSON (blocked by WAF?)") from e

        rows = payload.get("stockData", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            raise ScrapeError("unexpected ticker feed format")

        df = pd.DataFrame(rows)
        rename = {}
        for col in df.columns:
            lc = col.lower()
            if lc in ("pk_rf_company", "companysymbol", "symbol", "companyref"):
                rename[col] = "symbol"
            elif lc in ("companyshortnameen", "companynameen", "shortname"):
                rename[col] = "name"
            elif lc in ("lasttradeprice", "lastprice", "price"):
                rename[col] = "price"
            elif lc in ("changepercent", "percentagechange", "changeper"):
                rename[col] = "change_pct"
            elif lc in ("changevalue", "change", "netchange"):
                rename[col] = "change"
        df = df.rename(columns=rename)
        keep = [c for c in ("symbol", "name", "price", "change", "change_pct") if c in df.columns]
        df = df[keep].copy()
        if "symbol" in df:
            df["symbol"] = df["symbol"].astype(str).str.strip()
        for c in ("price", "change", "change_pct"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.drop_duplicates("symbol") if "symbol" in df else df

    # ------------------------------------------------------------ historical
    def _find_history_url(self, symbol: str) -> tuple[str, str]:
        page = self._request("GET", COMPANY_URL, params={"companySymbol": symbol}).text
        m = _HIST_URL_RE.search(page)
        if not m:
            # Some versions put the URL in a data-* attribute of the tab/form.
            soup = BeautifulSoup(page, "html.parser")
            for tag in soup.find_all(attrs=True):
                for v in tag.attrs.values():
                    if isinstance(v, str) and "historical" in v.lower() and "/wps/portal/" in v:
                        return BASE_URL + v[v.index("/wps/portal/"):], page
            raise ScrapeError(
                f"could not locate the historical-data endpoint on the profile page for {symbol}; "
                "the site layout may have changed (try --source yahoo)"
            )
        return BASE_URL + m.group("url").replace("&amp;", "&"), page

    def get_history_tadawul(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self._warm_up()
        url, _ = self._find_history_url(symbol)
        form = {
            "draw": "1",
            "start": "0",
            "length": "5000",
            "search[value]": "",
            "search[regex]": "false",
            "symbol": symbol,
            "companySymbol": symbol,
            "fromDate": start.strftime("%Y-%m-%d"),
            "toDate": end.strftime("%Y-%m-%d"),
        }
        headers = {
            "Referer": f"{COMPANY_URL}?companySymbol={symbol}",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        r = self._request("POST", url, data=form, headers=headers)
        try:
            payload = r.json()
        except ValueError:
            # Some portlets wrap JSON in HTML; try to extract the array.
            m = re.search(r"\{.*\}", r.text, re.S)
            if not m:
                raise ScrapeError("historical endpoint did not return JSON")
            payload = json.loads(m.group(0))
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not rows:
            raise ScrapeError(f"no historical rows returned for {symbol}")
        return normalise_ohlcv(pd.DataFrame(rows))

    def get_history_yahoo(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        params = {
            "period1": int(pd.Timestamp(start).timestamp()),
            "period2": int(pd.Timestamp(end + timedelta(days=1)).timestamp()),
            "interval": "1d",
        }
        r = self._request("GET", YAHOO_URL.format(symbol=symbol), params=params)
        res = r.json()["chart"]["result"]
        if not res:
            raise ScrapeError(f"Yahoo returned no data for {symbol}.SR")
        res = res[0]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame(
            {k: q[k] for k in ("open", "high", "low", "close", "volume")},
            index=pd.to_datetime(res["timestamp"], unit="s").normalize(),
        )
        df.index.name = "date"
        return df.dropna(subset=["close"])

    def get_history(self, symbol: str, days: int = 400, source: str = "auto") -> tuple[pd.DataFrame, str]:
        """Daily OHLCV for ``symbol`` (e.g. "2222"). Returns (frame, source_used)."""
        end = date.today()
        start = end - timedelta(days=days)
        errors = []
        order = {"tadawul": ["tadawul"], "yahoo": ["yahoo"], "auto": ["tadawul", "yahoo"]}[source]
        for src in order:
            try:
                fn = self.get_history_tadawul if src == "tadawul" else self.get_history_yahoo
                return fn(symbol, start, end), src
            except (ScrapeError, requests.RequestException, KeyError, ValueError) as e:
                errors.append(f"{src}: {e}")
        raise ScrapeError("all sources failed:\n  " + "\n  ".join(errors))


def _pick(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _to_number(s: pd.Series) -> pd.Series:
    if not pd.api.types.is_numeric_dtype(s):
        s = s.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce")


def normalise_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """Map arbitrary Tadawul/CSV column names onto date-indexed open/high/low/close/volume."""
    cols = {}
    for target, aliases in FIELD_ALIASES.items():
        c = _pick(raw, aliases)
        if c is None and target not in ("open", "volume"):
            raise ScrapeError(f"column for '{target}' not found in {list(raw.columns)}")
        cols[target] = c
    out = pd.DataFrame(index=pd.to_datetime(raw[cols["date"]], errors="coerce", dayfirst=False))
    for target in ("open", "high", "low", "close", "volume"):
        out[target] = _to_number(raw[cols[target]]).values if cols[target] else float("nan")
    out.index.name = "date"
    out = out[out.index.notna()].dropna(subset=["high", "low", "close"])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def load_csv(path: str | Path) -> pd.DataFrame:
    return normalise_ohlcv(pd.read_csv(path))
