"""Downloads the 10-K filings for the example into library/raw/.

    python fetch_filings.py

The filings are public and need no API key. EDGAR just wants a descriptive
User-Agent and no more than 10 requests a second. Stdlib only, so it runs on a
clean checkout.

It walks three JSON endpoints to find each filing:
  1. ticker -> CIK   https://www.sec.gov/files/company_tickers.json
  2. CIK -> filings  https://data.sec.gov/submissions/CIK{cik:010d}.json
  3. the .htm        https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}

Fiscal year comes from each filing's reportDate. For these five companies that
matches how they label their own fiscal year (NVIDIA's FY2024 ends Jan 2024).
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

# EDGAR requires a descriptive User-Agent identifying the requester; requests
# without one get a 403. Change the email to your own if you re-run this.
USER_AGENT = "reigner-example ananthanandanan@gmail.com"

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
FISCAL_YEARS = frozenset({2022, 2023, 2024})

RAW_DIR = Path(__file__).parent / "library" / "raw"
REQUEST_INTERVAL_S = 0.2  # >= 5 gaps/sec keeps us well under EDGAR's 10 req/s.

_last_request = 0.0


def _get(url: str) -> bytes:
    """Fetch a URL with the required UA header, throttled to be polite."""
    global _last_request
    wait = REQUEST_INTERVAL_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        _last_request = time.monotonic()
        return response.read()


def _get_json(url: str) -> dict:
    return json.loads(_get(url))


def ticker_to_cik() -> dict[str, int]:
    """Map every EDGAR ticker to its integer CIK."""
    data = _get_json("https://www.sec.gov/files/company_tickers.json")
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def _iter_10k(block: dict) -> Iterator[tuple[int, str, str]]:
    for form, accession, document, report_date in zip(
        block["form"],
        block["accessionNumber"],
        block["primaryDocument"],
        block["reportDate"],
        strict=False,
    ):
        if form != "10-K":
            continue
        yield int(report_date[:4]), accession.replace("-", ""), document


def ten_k_filings(cik: int) -> Iterator[tuple[int, str, str]]:
    """Yield (fiscal_year, accession, primary_document) for each of a CIK's 10-Ks.

    Heavy filers like Alphabet bump older 10-Ks out of the `recent` list into
    the extra files under `filings.files`, so read those too or you'll miss a
    year.
    """
    subs = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    yield from _iter_10k(subs["filings"]["recent"])
    for overflow in subs["filings"].get("files", []):
        block = _get_json(f"https://data.sec.gov/submissions/{overflow['name']}")
        yield from _iter_10k(block)


def main() -> None:
    """Download every target filing, printing what it grabbed."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cik_map = ticker_to_cik()

    for ticker in TICKERS:
        cik = cik_map[ticker]
        collected: set[int] = set()
        for fiscal_year, accession, document in ten_k_filings(cik):
            if fiscal_year not in FISCAL_YEARS or fiscal_year in collected:
                continue
            collected.add(fiscal_year)
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
            dest = RAW_DIR / f"{ticker.lower()}-{fiscal_year}.htm"
            dest.write_bytes(_get(url))
            print(f"  {ticker} FY{fiscal_year}  ->  {dest.name}  ({url})")
        missing = sorted(FISCAL_YEARS - collected)
        if missing:
            print(f"  ! {ticker}: no 10-K found for fiscal year(s) {missing}")


if __name__ == "__main__":
    main()
