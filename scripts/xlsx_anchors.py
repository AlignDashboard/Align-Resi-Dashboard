"""Locate data in a spreadsheet by its labels rather than by fixed coordinates.

The Landing workbook is regenerated each period from the same report templates,
but row and column counts move: a month is added, a lease is signed, a holdover
is repriced. Fixed coordinates survive none of that, and they fail silently —
reading a month as the TTM column, or pulling a "Total" row into a unit list.

Everything here anchors on a label and stops at a sentinel, so a block that
grows or shifts is still read correctly, and one that disappears raises instead
of returning a plausible wrong number.
"""
import datetime
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


class LayoutError(Exception):
    """A label or block the extractor depends on is not where it should be."""


def norm(v):
    """Normalize a cell to a comparable label: collapse whitespace, casefold."""
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip().casefold()


def cell(ws, row, col):
    v = ws.cell(row=row, column=col).value
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        return round(v, 6)
    return v


def find_row(ws, label, col=2, after=1, before=None, exact=True, required=True):
    """Row number whose `col` holds `label`. Raises if required and absent.

    `after`/`before` scope the search so repeated labels in different sections
    (Rent Capture has "Vacancy loss" in both the dollar and percent blocks) can
    be told apart.
    """
    want = norm(label)
    last = before if before is not None else ws.max_row
    for r in range(after, last + 1):
        got = norm(ws.cell(row=r, column=col).value)
        if (got == want) if exact else (want in got):
            return r
    if required:
        raise LayoutError(
            f"{ws.title!r}: no row with {'label' if exact else 'text'} "
            f"{label!r} in column {col} between rows {after} and {last}")
    return None


def parse_month(v):
    """'Jan 2025' | '2026-08' | a date -> 'YYYY-MM'. None if not a month."""
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m")
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})(-\d{2})?", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1)[:3].lower()]:02d}"
    return None


def month_axis(ws, header_row, first_col=3, ttm_pattern="ttm"):
    """Month columns and the TTM column, both found by reading the header.

    Returns (months, cols, ttm_col) where months[i] is the 'YYYY-MM' for cols[i].
    Stops at the first cell matching `ttm_pattern`, so adding a month moves the
    TTM column without the caller needing to know.
    """
    months, cols, ttm_col = [], [], None
    for c in range(first_col, ws.max_column + 1):
        raw = ws.cell(row=header_row, column=c).value
        if raw is None:
            if months:
                continue
            continue
        if ttm_pattern in norm(raw):
            ttm_col = c
            break
        mo = parse_month(raw)
        if mo:
            months.append(mo)
            cols.append(c)
    if not months:
        raise LayoutError(f"{ws.title!r}: no month columns found on row {header_row}")
    if ttm_col is None:
        raise LayoutError(
            f"{ws.title!r}: month columns end at {cols[-1]} but no column "
            f"matching {ttm_pattern!r} follows — the TTM column has moved or gone")
    gaps = [i for i in range(1, len(months)) if not _is_next_month(months[i - 1], months[i])]
    if gaps:
        raise LayoutError(
            f"{ws.title!r}: month columns are not consecutive around "
            + ", ".join(f"{months[i-1]}->{months[i]}" for i in gaps))
    return months, cols, ttm_col


def _is_next_month(a, b):
    ya, ma = (int(x) for x in a.split("-"))
    yb, mb = (int(x) for x in b.split("-"))
    return (yb, mb) == ((ya + 1, 1) if ma == 12 else (ya, ma + 1))


def series(ws, row, cols):
    return [cell(ws, row, c) for c in cols]


def labelled_series(ws, label, cols, col=2, after=1, before=None):
    return series(ws, find_row(ws, label, col=col, after=after, before=before), cols)


def scalar(ws, label, value_col=3, col=2, after=1, before=None, exact=True, required=True):
    r = find_row(ws, label, col=col, after=after, before=before, exact=exact,
                 required=required)
    return cell(ws, r, value_col) if r else None


def block(ws, header_row, cols, label_col=2, stop_labels=("total",),
          stop_on_blank=True, keep=None, max_rows=5000):
    """Rows beneath a header until a sentinel label or a blank run.

    `keep(values)` filters rows that are present but not data — a summary line
    inside the same column, for instance. Returns a list of value lists.
    """
    stops = {norm(s) for s in stop_labels}
    out, blanks = [], 0
    for r in range(header_row + 1, min(ws.max_row, header_row + max_rows) + 1):
        label = ws.cell(row=r, column=label_col).value
        if label is None or norm(label) == "":
            blanks += 1
            if stop_on_blank and blanks >= 1:
                break
            continue
        blanks = 0
        if norm(label) in stops:
            break
        vals = [cell(ws, r, c) for c in cols]
        if keep is None or keep(vals):
            out.append(vals)
    return out


def is_stale(ws_list, probes):
    """True when the workbook's cached formula results are missing.

    openpyxl reads cached values; a workbook edited without a recalculation has
    none, so every derived number comes back None. Detecting that is the
    difference between a loud failure and a dashboard full of nulls.
    """
    missing = 0
    for ws, label, col in probes:
        try:
            if scalar(ws, label, value_col=col) is None:
                missing += 1
        except LayoutError:
            missing += 1
    return missing, len(probes)
