"""Command-line interface.

Examples:
    python -m tadawul_ichimoku list                     # latest prices for all stocks
    python -m tadawul_ichimoku analyze 2222 --plot      # Saudi Aramco
    python -m tadawul_ichimoku analyze 1120 2010 7010   # several symbols
    python -m tadawul_ichimoku analyze 2222 --csv my_prices.csv
    python -m tadawul_ichimoku serve                    # web app on http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ichimoku import IchimokuParams, analyze, compute_ichimoku, format_report
from .plot import plot_ichimoku
from .scraper import ScrapeError, TadawulScraper, load_csv


def cmd_list(args: argparse.Namespace) -> int:
    df = TadawulScraper().get_market_snapshot()
    if args.top and "change_pct" in df:
        df = df.sort_values("change_pct", ascending=False).head(args.top)
    print(df.to_string(index=False))
    if args.save:
        df.to_csv(args.save, index=False)
        print(f"\nSaved to {args.save}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    params = IchimokuParams(args.tenkan, args.kijun, args.senkou_b, args.displacement)
    scraper = TadawulScraper()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    names: dict[str, str] = {}
    if not args.csv:
        try:
            snap = scraper.get_market_snapshot()
            if {"symbol", "name"} <= set(snap.columns):
                names = dict(zip(snap["symbol"], snap["name"]))
        except ScrapeError:
            pass  # names are cosmetic

    failures = 0
    summary = []
    for symbol in args.symbols:
        try:
            if args.csv:
                df, src = load_csv(args.csv), f"csv:{args.csv}"
            else:
                df, src = scraper.get_history(symbol, days=args.days, source=args.source)
                df.to_csv(out_dir / f"{symbol}_prices.csv")
            ich = compute_ichimoku(df, params)
            rep = analyze(ich, params)
        except (ScrapeError, ValueError) as e:
            print(f"[{symbol}] ERROR: {e}", file=sys.stderr)
            failures += 1
            continue

        print(format_report(symbol, names.get(symbol), rep))
        print(f" Data source: {src}, {len(df)} trading days")
        ich.to_csv(out_dir / f"{symbol}_ichimoku.csv")
        if args.plot:
            title = f"{symbol} {names.get(symbol, '')} - Ichimoku ({rep.date.date()})".replace("  ", " ")
            path = plot_ichimoku(ich, title, str(out_dir / f"{symbol}_ichimoku.png"))
            print(f" Chart: {path}")
        print()
        summary.append((symbol, rep.close, rep.score, rep.verdict))

    if len(summary) > 1:
        print("Summary")
        for sym, close, score, verdict in sorted(summary, key=lambda x: -x[2]):
            print(f"  {sym:<6} {close:>9.2f}  {score:+d}  {verdict}")
    return 1 if failures else 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web.app import run

    print(f"Tadawul Ichimoku running at http://{args.host}:{args.port}")
    run(host=args.host, port=args.port, debug=args.debug)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tadawul_ichimoku", description="Saudi Exchange scraper + Ichimoku analysis")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("list", help="latest prices of all listed companies")
    pl.add_argument("--top", type=int, help="show only the N biggest gainers")
    pl.add_argument("--save", help="write the snapshot to this CSV")
    pl.set_defaults(func=cmd_list)

    pa = sub.add_parser("analyze", help="Ichimoku analysis for one or more symbols")
    pa.add_argument("symbols", nargs="+", help="Tadawul symbols, e.g. 2222 1120")
    pa.add_argument("--days", type=int, default=400, help="calendar days of history to fetch (default 400)")
    pa.add_argument("--source", choices=["auto", "tadawul", "yahoo"], default="auto")
    pa.add_argument("--csv", help="analyse a local CSV (date,open,high,low,close,volume) instead of scraping")
    pa.add_argument("--plot", action="store_true", help="save a PNG chart")
    pa.add_argument("--out", default="output", help="output directory (default ./output)")
    pa.add_argument("--tenkan", type=int, default=9)
    pa.add_argument("--kijun", type=int, default=26)
    pa.add_argument("--senkou-b", type=int, default=52)
    pa.add_argument("--displacement", type=int, default=26)
    pa.set_defaults(func=cmd_analyze)

    ps = sub.add_parser("serve", help="start the web application")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=5000)
    ps.add_argument("--debug", action="store_true")
    ps.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ScrapeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
