import csv
import hashlib
import io
import json
import re
from datetime import datetime


_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")

_DATE_FIELDS = (
    "date",
    "activity date",
    "transaction date",
    "trade date",
    "timestamp",
    "date executed",
    "transaction date and time",
)
_SYMBOL_FIELDS = ("symbol", "instrument", "ticker", "asset")
_TYPE_FIELDS = ("type", "activity type", "action", "side", "transaction type", "trans code")
_QUANTITY_FIELDS = ("quantity", "qty", "shares")
_PRICE_FIELDS = ("price", "average price", "fill price", "trade price")
_TOTAL_FIELDS = ("total", "amount", "net amount", "proceeds")
_DESCRIPTION_FIELDS = ("description", "details", "notes")


def _decode_csv_bytes(content):
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if hasattr(content, "read"):
        content = content.read()
    if isinstance(content, bytearray):
        content = bytes(content)
    if not isinstance(content, (bytes, bytearray)):
        return str(content)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _normalize_header(value):
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _find_column(row, candidates):
    lookup = {_normalize_header(key): key for key in (row or {}).keys()}
    for candidate in candidates:
        key = lookup.get(_normalize_header(candidate))
        if key:
            return key
    return None


def _strip_text(value):
    return str(value or "").strip()


def _parse_float(value):
    text = _strip_text(value)
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _parse_datetime_text(value):
    text = _strip_text(value)
    if not text:
        return ""
    candidates = [
        text,
        text.replace("Z", "+00:00"),
    ]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text


def _infer_trade_side(type_text, description_text, quantity, total):
    combined = " ".join(part for part in [type_text, description_text] if part).strip().lower()
    if any(token in combined for token in ("dividend", "transfer", "deposit", "withdraw", "interest", "wire", "fee")):
        return None
    if any(token in combined for token in ("option", "call", "put", "contract")):
        return None
    if any(token in combined for token in ("sell", "sold")):
        return "SELL"
    if any(token in combined for token in ("buy", "bought", "reinvest", "reinvestment")):
        return "BUY"
    if quantity is not None and quantity < 0:
        return "SELL"
    if total is not None and total < 0:
        return "BUY"
    if quantity is not None and quantity > 0:
        return "BUY"
    return None


def _infer_cash_event(type_text, description_text, total):
    combined = " ".join(part for part in [type_text, description_text] if part).strip().lower()
    if not combined:
        return None
    if any(token in combined for token in ("dividend",)):
        return "DIVIDEND"
    if any(token in combined for token in ("interest",)):
        return "INTEREST"
    if any(token in combined for token in ("fee", "commission", "regulatory", "adr")):
        return "FEE"
    if any(token in combined for token in ("withdraw", "withdrawal", "wire sent")):
        return "CASH_WITHDRAWAL"
    if any(token in combined for token in ("deposit", "cash transfer", "transfer in", "wire received", "ach")):
        if total is None or float(total) >= 0:
            return "CASH_DEPOSIT"
        return "CASH_WITHDRAWAL"
    return None


def _canonical_number_text(value):
    if value is None:
        return ""
    return f"{float(value):.8f}".rstrip("0").rstrip(".")


def _build_import_key(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_trade_record(row, *, filename=""):
    date_column = _find_column(row, _DATE_FIELDS)
    symbol_column = _find_column(row, _SYMBOL_FIELDS)
    type_column = _find_column(row, _TYPE_FIELDS)
    quantity_column = _find_column(row, _QUANTITY_FIELDS)
    price_column = _find_column(row, _PRICE_FIELDS)
    total_column = _find_column(row, _TOTAL_FIELDS)
    description_column = _find_column(row, _DESCRIPTION_FIELDS)

    date_value = _parse_datetime_text(row.get(date_column)) if date_column else ""
    symbol = _strip_text(row.get(symbol_column)).upper() if symbol_column else ""
    type_text = _strip_text(row.get(type_column)) if type_column else ""
    description_text = _strip_text(row.get(description_column)) if description_column else ""
    quantity = _parse_float(row.get(quantity_column)) if quantity_column else None
    price = _parse_float(row.get(price_column)) if price_column else None
    total = _parse_float(row.get(total_column)) if total_column else None

    if not date_value:
        return None, "missing date"
    side = _infer_trade_side(type_text, description_text, quantity, total)
    if side not in {"BUY", "SELL"}:
        cash_event_type = _infer_cash_event(type_text, description_text, total)
        if cash_event_type:
            amount = float(total) if total is not None else None
            if amount is None:
                return None, "missing cash amount"
            if cash_event_type in {"CASH_WITHDRAWAL", "FEE"}:
                amount = -abs(amount)
            elif cash_event_type in {"CASH_DEPOSIT", "DIVIDEND", "INTEREST"}:
                amount = abs(amount)
            fingerprint_payload = {
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                "date": date_value,
                "event_type": cash_event_type,
                "symbol": symbol,
                "amount": _canonical_number_text(amount),
                "description": description_text.lower(),
            }
            notes = description_text or f"Imported from Robinhood account activity CSV ({filename or 'upload'})"
            return {
                "record_type": "CASH_EVENT",
                "event_type": cash_event_type,
                "side": "",
                "date": date_value,
                "symbol": symbol,
                "shares": None,
                "price": None,
                "sell_price": None,
                "cost_basis": None,
                "proceeds": float(amount),
                "pl": None,
                "pl_pct": None,
                "notes": notes,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                "import_key": _build_import_key(fingerprint_payload),
                "source_file": str(filename or ""),
            }, None
        return None, "unsupported activity type"

    if not symbol or not _SYMBOL_PATTERN.match(symbol):
        return None, "unsupported or missing symbol"
    if quantity is None or quantity == 0:
        return None, "missing quantity"

    quantity = abs(float(quantity))
    if price is None and total is not None and quantity > 0:
        price = abs(float(total)) / quantity
    if price is None:
        return None, "missing price"

    fingerprint_payload = {
        "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
        "date": date_value,
        "symbol": symbol,
        "side": side,
        "shares": _canonical_number_text(quantity),
        "price": _canonical_number_text(price),
        "total": _canonical_number_text(abs(total) if total is not None else None),
        "type": type_text.lower(),
        "description": description_text.lower(),
    }

    notes = description_text or f"Imported from Robinhood account activity CSV ({filename or 'upload'})"
    record = {
        "record_type": "TRADE",
        "event_type": side,
        "side": side,
        "date": date_value,
        "symbol": symbol,
        "shares": quantity,
        "price": float(price),
        "sell_price": float(price) if side == "SELL" else None,
        "cost_basis": float(price) if side == "BUY" else None,
        "proceeds": abs(float(total)) if side == "SELL" and total is not None else None,
        "pl": None,
        "pl_pct": None,
        "notes": notes,
        "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
        "import_key": _build_import_key(fingerprint_payload),
        "source_file": str(filename or ""),
    }
    return record, None


def parse_robinhood_activity_csv(content, *, filename=""):
    text = _decode_csv_bytes(content)
    reader = csv.DictReader(io.StringIO(text))
    records = []
    skipped_rows = []
    for row_number, row in enumerate(reader, start=2):
        record, skip_reason = _build_trade_record(row or {}, filename=filename)
        if record is None:
            skipped_rows.append(
                {
                    "row_number": row_number,
                    "reason": skip_reason or "unsupported row",
                }
            )
            continue
        records.append(record)

    return {
        "records": records,
        "parsed_count": len(records),
        "skipped_rows": skipped_rows,
        "skipped_count": len(skipped_rows),
        "filename": str(filename or ""),
    }
