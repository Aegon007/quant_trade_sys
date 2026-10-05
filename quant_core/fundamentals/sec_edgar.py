from __future__ import annotations

import json
import hashlib
import os
import re
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
DEFAULT_CACHE_DIR = qpaths.RESEARCH_CACHE_DIR / "sec"
PERIODIC_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
CURRENT_FORMS = {"8-K", "6-K"}
DECISION_SECTION_TERMS = (
    "risk factors",
    "management's discussion",
    "management’s discussion",
    "quantitative and qualitative disclosures",
    "liquidity and capital resources",
    "business",
)


def _headers(user_agent: Optional[str] = None) -> dict:
    agent = str(user_agent or os.getenv("SEC_USER_AGENT") or "personal-valuation-research contact@example.com").strip()
    return {"User-Agent": agent, "Host": "www.sec.gov"}


def _read_json(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload


def _fetch_json(url: str, *, user_agent: Optional[str], urlopen, host: Optional[str] = None):
    headers = _headers(user_agent)
    if host:
        headers["Host"] = host
    request = urllib.request.Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(data, encoding="utf-8")
    temporary.replace(path)


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_of_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return _parse_date(value) or datetime.now().date()


def _recent_submission_rows(payload: Mapping) -> list[dict]:
    recent = dict(dict(payload.get("filings", {}) or {}).get("recent", {}) or {})
    size = max((len(value) for value in recent.values() if isinstance(value, list)), default=0)
    rows = []
    for index in range(size):
        row = {}
        for key, values in recent.items():
            if isinstance(values, list) and index < len(values):
                row[key] = values[index]
        form = str(row.get("form") or "").strip().upper()
        if form:
            row["form"] = form.removesuffix("/A")
            row["filing_date"] = str(row.get("filingDate") or "")
            row["report_date"] = str(row.get("reportDate") or "")
            row["accession_number"] = str(row.get("accessionNumber") or "")
            row["primary_document"] = str(row.get("primaryDocument") or "")
            rows.append(row)
    return rows


def select_relevant_filings(payload: Mapping, *, as_of=None, max_documents: int = 2) -> list[dict]:
    """Select the latest periodic filing and a newer earnings current report."""
    cutoff = _as_of_date(as_of)
    rows = [
        row
        for row in _recent_submission_rows(payload)
        if _parse_date(row.get("filing_date"))
        and _parse_date(row.get("filing_date")) <= cutoff
        and row.get("accession_number")
        and row.get("primary_document")
    ]
    rows.sort(key=lambda row: (_parse_date(row.get("filing_date")) or date.min), reverse=True)
    periodic = next((row for row in rows if row["form"] in PERIODIC_FORMS), None)
    selected = [periodic] if periodic else []
    periodic_date = _parse_date((periodic or {}).get("filing_date")) or date.min
    current = next(
        (
            row
            for row in rows
            if row["form"] in CURRENT_FORMS
            and (_parse_date(row.get("filing_date")) or date.min) >= periodic_date
            and (row["form"] == "6-K" or any(code in str(row.get("items") or "") for code in ("2.02", "7.01", "8.01")))
        ),
        None,
    )
    if current and current not in selected:
        selected.append(current)
    if not selected and rows:
        selected.append(rows[0])
    return [dict(row) for row in selected[: max(int(max_documents), 1)]]


def build_filing_document_url(*, cik: str, accession_number: str, primary_document: str) -> str:
    normalized_cik = str(int(str(cik).strip()))
    accession = re.sub(r"[^0-9]", "", str(accession_number or ""))
    document = str(primary_document or "").strip().lstrip("/")
    if not accession or not document:
        raise ValueError("accession_number and primary_document are required")
    return FILING_ARCHIVE_URL.format(cik=normalized_cik, accession=accession, document=document)


def _document_lines(html_text: str) -> list[str]:
    try:
        from lxml import html

        tree = html.fromstring(str(html_text or "").encode("utf-8"))
        for element in tree.xpath("//script|//style|//noscript|//*[contains(@style, 'display:none')]"):
            element.drop_tree()
        nodes = tree.xpath("//h1|//h2|//h3|//h4|//h5|//h6|//p|//li|//tr")
        lines = [" ".join(node.text_content().split()) for node in nodes]
        if not lines:
            lines = [" ".join(tree.text_content().split())]
    except Exception:
        lines = [" ".join(re.sub(r"<[^>]+>", " ", str(html_text or "")).split())]
    output = []
    for line in lines:
        if line and (not output or line != output[-1]):
            output.append(line)
    return output


def extract_filing_sections(html_text: str, *, form: str, max_section_chars: int = 7000, max_sections: int = 5) -> list[dict]:
    """Extract decision-relevant narrative sections without retaining inline-XBRL noise."""
    lines = _document_lines(html_text)
    headings = []
    heading_pattern = re.compile(r"^\s*(?:part\s+[ivx]+\s+)?item\s+(\d+[a-z]?)\s*[.\-:]?\s*(.{0,180})$", re.IGNORECASE)
    for index, line in enumerate(lines):
        match = heading_pattern.match(line)
        if match:
            headings.append((index, match.group(1).upper(), line))
    candidates = []
    for position, (start, item, title) in enumerate(headings):
        normalized_title = title.lower()
        if not any(term in normalized_title for term in DECISION_SECTION_TERMS):
            continue
        end = len(lines)
        for next_start, next_item, _next_title in headings[position + 1 :]:
            if next_item != item:
                end = next_start
                break
        body = "\n".join(lines[start + 1 : end]).strip()
        if len(body) < 40:
            continue
        candidates.append(
            {
                "item": item,
                "title": title[:220],
                "text": body[: max(int(max_section_chars), 500)],
                "original_char_count": len(body),
                "truncated": len(body) > max_section_chars,
                "_start": start,
            }
        )
    best_by_item = {}
    for section in candidates:
        current = best_by_item.get(section["item"])
        if current is None or section["original_char_count"] > current["original_char_count"]:
            best_by_item[section["item"]] = section
    sections = sorted(best_by_item.values(), key=lambda section: section["_start"])
    for section in sections:
        section.pop("_start", None)
    if sections:
        return sections[: max(int(max_sections), 1)]
    fallback = "\n".join(lines).strip()
    return ([{"item": "OVERVIEW", "title": f"{form} document overview", "text": fallback[:max_section_chars], "original_char_count": len(fallback), "truncated": len(fallback) > max_section_chars}] if fallback else [])


def fetch_submission_history(
    symbol: str,
    *,
    cik: Optional[str] = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    user_agent: Optional[str] = None,
    urlopen=urllib.request.urlopen,
    force: bool = False,
    max_age_seconds: int = 24 * 3600,
) -> dict:
    symbol = str(symbol or "").strip().upper()
    cache_dir = Path(cache_dir)
    path = cache_dir / "submissions" / f"{symbol}.json"
    if path.exists() and not force and time.time() - path.stat().st_mtime <= max_age_seconds:
        payload = _read_json(path)
        if isinstance(payload, dict):
            return payload
    resolved_cik = str(cik or load_ticker_map(cache_dir=cache_dir, user_agent=user_agent, urlopen=urlopen).get(symbol) or "").zfill(10)
    if not resolved_cik.strip("0"):
        raise LookupError(f"SEC CIK not found for {symbol}")
    payload = _fetch_json(SUBMISSIONS_URL.format(cik=resolved_cik), user_agent=user_agent, urlopen=urlopen, host="data.sec.gov")
    _atomic_write(path, json.dumps(payload))
    return payload


def fetch_filing_context(
    symbol: str,
    *,
    cik: Optional[str] = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    user_agent: Optional[str] = None,
    urlopen=urllib.request.urlopen,
    force: bool = False,
    as_of=None,
    max_documents: int = 2,
) -> dict:
    symbol = str(symbol or "").strip().upper()
    payload = fetch_submission_history(symbol, cik=cik, cache_dir=cache_dir, user_agent=user_agent, urlopen=urlopen, force=force)
    resolved_cik = str(payload.get("cik") or cik or "").zfill(10)
    filings, errors = [], []
    for row in select_relevant_filings(payload, as_of=as_of, max_documents=max_documents):
        try:
            url = build_filing_document_url(cik=resolved_cik, accession_number=row["accession_number"], primary_document=row["primary_document"])
            path = Path(cache_dir) / "filings" / str(int(resolved_cik)) / re.sub(r"[^0-9]", "", row["accession_number"]) / Path(row["primary_document"]).name
            if path.exists() and not force:
                html_text = path.read_text(encoding="utf-8", errors="replace")
            else:
                request = urllib.request.Request(url, headers=_headers(user_agent))
                with urlopen(request, timeout=30) as response:
                    html_text = response.read().decode("utf-8", errors="replace")
                _atomic_write(path, html_text)
            sections = extract_filing_sections(html_text, form=row["form"])
            filings.append(
                {
                    "form": row["form"],
                    "filing_date": row["filing_date"],
                    "report_date": row.get("report_date"),
                    "accession_number": row["accession_number"],
                    "primary_document": row["primary_document"],
                    "url": url,
                    "cache_path": str(path),
                    "sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
                    "sections": sections,
                }
            )
        except Exception as exc:
            errors.append({"form": row.get("form"), "filing_date": row.get("filing_date"), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "status": "READY" if filings else "UNAVAILABLE",
        "source": "sec_edgar_filing",
        "retrieved_at": datetime.now().isoformat(),
        "filings": filings,
        "errors": errors,
    }


def load_ticker_map(
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    user_agent: Optional[str] = None,
    urlopen=urllib.request.urlopen,
    max_age_seconds: int = 7 * 24 * 3600,
) -> dict[str, str]:
    cache_dir = Path(cache_dir)
    path = cache_dir / "company_tickers.json"
    payload = None
    if path.exists() and time.time() - path.stat().st_mtime <= max_age_seconds:
        payload = _read_json(path)
    if payload is None:
        payload = _fetch_json(TICKER_MAP_URL, user_agent=user_agent, urlopen=urlopen)
        _atomic_write(path, json.dumps(payload))
    rows = payload.values() if isinstance(payload, Mapping) else []
    return {
        str(row.get("ticker") or "").strip().upper(): str(int(row.get("cik_str"))).zfill(10)
        for row in rows
        if isinstance(row, Mapping) and row.get("ticker") and row.get("cik_str") is not None
    }


def fetch_company_facts(
    symbol: str,
    *,
    cik: Optional[str] = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    user_agent: Optional[str] = None,
    urlopen=urllib.request.urlopen,
    force: bool = False,
    max_age_seconds: int = 24 * 3600,
) -> dict:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    cache_dir = Path(cache_dir)
    path = cache_dir / "companyfacts" / f"{symbol}.json"
    if path.exists() and not force and time.time() - path.stat().st_mtime <= max_age_seconds:
        payload = _read_json(path)
        if isinstance(payload, dict):
            return payload
    resolved_cik = str(cik or load_ticker_map(cache_dir=cache_dir, user_agent=user_agent, urlopen=urlopen).get(symbol) or "").zfill(10)
    if not resolved_cik.strip("0"):
        raise LookupError(f"SEC CIK not found for {symbol}")
    payload = _fetch_json(
        COMPANY_FACTS_URL.format(cik=resolved_cik),
        user_agent=user_agent,
        urlopen=urlopen,
        host="data.sec.gov",
    )
    _atomic_write(path, json.dumps(payload))
    return payload
