"""
parse_t12_statement.py
----------------------
Parses a Yardi 12-Month (T12) Statement export and extracts the expense-ratio
inputs. Anchors on Yardi ACCOUNT CODES (column A), not row positions, so it is
robust to suppress-zero exports and minor layout shifts.

Expense ratio (per Align definition) =
    TOTAL OPERATING EXPENSE RECOVERABLE (code 5999-9998)
    -------------------------------------------------------
    TOTAL OPERATING REVENUE            (code 4999-9999)

Usage:
    from parse_t12_statement import parse_t12
    result = parse_t12("path/to/statement.xlsx")
"""

import os
import re
import sys
import json
import openpyxl

# JPM->Align chart-of-accounts mapping, extracted from the owner's COA workbook
# by scripts/extract_coa_map.py. Loaded lazily so align-tree statements never
# need it; a jpm-tree statement without it refuses buckets rather than guessing.
COA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "coa_map.json")
_COA = None


def _coa():
    global _COA
    if _COA is None:
        _COA = json.load(open(COA_PATH))
    return _COA

# Yardi rollup account codes we anchor on, per account tree. The Align tree
# (align_resbv) is what Palma and 335 Third report on; The Landing's statement
# arrives on the JPM tree (jpm_bf1) with six-digit accounts, and its expenses
# are translated back to the Align tree through config/coa_map.json.
CODE_REVENUE = "4999-9999"   # align: TOTAL OPERATING REVENUE
CODE_OPEX    = "5999-9998"   # align: TOTAL OPERATING EXPENSE RECOVERABLE
JPM_REVENUE  = "499999-9999" # jpm: TOTAL REVENUE
JPM_OPEX     = "519999-9999" # jpm: TOTAL OPERATING EXPENSES
JPM_EXP_ALL  = "549999-9999" # jpm: TOTAL EXPENSES (operating + non-operating)

MONTHS_COLS = range(2, 14)   # columns C..N hold the 12 monthly values
TOTAL_COL   = 14             # column O holds the row total

# ---- expense buckets -------------------------------------------------------
# The Landing's Expense Deep Dive shows eleven analyst-defined buckets. The
# workbook publishes them as period aggregates only, so the monthly view is
# classified here from the statement's own GL detail. Classification is
# keyword-based and therefore an approximation of the analyst's hand grouping;
# what is NOT approximate is the total: the recoverable side must tie out
# against the statement's own 5999-9998 row month by month or buckets are
# refused for that file. First matching rule wins, so "payroll taxes and
# benefits" lands in payroll, not in taxes.
BUCKET_RULES = [
    ("Payroll & benefits", ("payroll", "salary", "salaries", "bonus",
                            "commission", "benefits")),
    ("Management fee", ("management fee", "mgmt fee")),
    ("Insurance", ("insurance",)),
    ("Real estate & other taxes", ("tax",)),
    ("Utilities (net of reimbursements)", ("electric", "gas", "water", "sewer",
                                           "trash", "refuse", "utilit", "cable",
                                           "telephone", "internet", "steam")),
    ("Turnover", ("turnover", "make ready", "make-ready", "unit prep",
                  "apartment turn")),
    ("Marketing & advertising", ("marketing", "advertis", "promo")),
    ("Professional fees", ("professional", "legal", "audit", "consult",
                           "accounting")),
    ("Contract services", ("contract", "cleaning", "security", "landscap",
                           "pest", "elevator")),
    ("Repairs & maintenance", ("repair", "maint", "hvac", "plumb",
                               "general building", "common area", "supplies")),
    ("Administrative", ("admin", "office", "bank fee", "software", "dues",
                        "license", "postage", "tenant experience",
                        "tenant engagement")),
]
BUCKET_OTHER = "Other / unclassified"

# Below-the-NOI-line sections that are not operating expense and must not be
# bucketed: financing, non-cash and capital items.
BELOW_LINE_EXCLUDE = ("interest", "depreciation", "amortization", "amortisation",
                      "capital", "debt service", "reserve", "asset management",
                      "partnership", "income tax provision")


# Display groups for the JPM-tree statement, defined on the ALIGN side of the
# COA mapping -- these are the Align account tree's own families (5110 Cleaning,
# 5137 Residential Turnover, 5300 Utilities, 5700 Taxes, 71xx non-recoverable
# twins, ...), so the deep dive reads in the tree's groupings rather than in
# keyword guesses. ADMIN (5170) splits by sub-code the way the tree itself
# names them: 3xxx payroll, 2350 mgmt fee, 2000/2250/2550 professional.
def _align_group(align_code, align_name):
    c = align_code
    pre = c.split("-")[0]
    suf = c.split("-")[1] if "-" in c else ""
    if pre in ("5700", "7190"):
        return "Taxes"
    if pre in ("5500", "7180"):
        return "Insurance"
    if pre in ("5300", "7140") or (pre == "4050" and suf.startswith("55")) or pre == "4630":
        return "Utilities (net of billbacks)"
    if pre == "5170" and suf.startswith("3"):
        return "Payroll & benefits"
    if pre in ("5173",):
        return "Payroll & benefits"
    if pre == "5170" and suf == "2350" or pre == "7200":
        return "Management fee"
    if pre == "5170" and suf in ("2000", "2250", "2550") or pre == "7400":
        return "Professional fees"
    if pre in ("5170", "5171", "7150"):
        return "Admin & office"
    if pre == "5110" or (pre == "7120" and suf.startswith("02")):
        return "Cleaning"
    if pre in ("5120", "5121", "5125", "7130", "7135"):
        return "Security & fire/life safety"
    if pre == "5137":
        return "Residential turnover"
    if pre in ("5150", "5151", "5152", "5153"):
        return "Tenant engagement"
    if pre.startswith("61"):
        return "Marketing & advertising"
    if pre in ("5130", "5131", "5132", "5133", "5134", "5135", "5136", "5140",
               "5141", "5142", "5145", "7101", "7120", "7121", "7122", "7123",
               "7124", "7125", "7127", "7160", "7170", "7195", "7660"):
        return "Repairs & maintenance"
    if pre == "7250":
        return "Bad debt"
    return None


# Fallback for JPM leaves the COA workbook does not map (they are listed in the
# output so the owner can extend the mapping): grouped by their own label.
_JPM_FALLBACK = [
    ("Residential turnover", ("turnover",)),
    ("Security & fire/life safety", ("patrol", "security", "alarm")),
    ("Tenant engagement", ("concierge", "courtesy")),
    ("Taxes", ("tax",)),
    ("Professional fees", ("professional", "legal", "accounting")),
    ("Admin & office", ("credit report", "credit card", "bank", "office")),
    ("Repairs & maintenance", ("carpet", "repair", "maint")),
]


def expense_buckets_jpm(rows):
    """The Landing's statement arrives on the JPM tree; its expense leaves are
    translated to Align accounts through config/coa_map.json and grouped by the
    Align tree's families. Region: 500000-0000 EXPENSES through 549999-9999
    TOTAL EXPENSES (operating + non-operating; financing and the balance sheet
    sit outside it). The tie-out is strict: every leaf is grouped somewhere,
    so the groups must sum to the statement's own TOTAL EXPENSES each month.
    """
    coa = _coa()["jpm"]
    months = 12
    buckets, unmapped, other = {}, [], []
    total = None
    in_exp = False
    for r in rows:
        code = str(r[0]).strip() if r and r[0] else ""
        label = str(r[1]).strip() if r and len(r) > 1 and r[1] else ""
        if code == "500000-0000":
            in_exp = True
            continue
        if code == JPM_EXP_ALL:
            total = [float(r[c]) if isinstance(r[c], (int, float)) else 0.0
                     for c in MONTHS_COLS]
            break
        if not in_exp or not code:
            continue
        vals = [float(r[c]) if len(r) > c and isinstance(r[c], (int, float))
                else None for c in MONTHS_COLS]
        if not any(v is not None for v in vals):
            continue
        if label.upper().startswith("TOTAL") or code[-2:] in ("98", "99"):
            continue
        mapped = coa.get(code)
        if mapped:
            grp = _align_group(mapped[0], mapped[1])
        else:
            unmapped.append(f"{code} {label}")
            grp = next((g for g, kws in _JPM_FALLBACK
                        if any(k in label.lower() for k in kws)), None)
        if grp is None:
            grp = "Other / unclassified"
            other.append(f"{code} {label}")
        tgt = buckets.setdefault(grp, [0.0] * months)
        for i, v in enumerate(vals):
            if v is not None:
                tgt[i] += v

    if total is None:
        raise ValueError(f"no {JPM_EXP_ALL} TOTAL EXPENSES row; cannot tie out")
    summed = [sum(vs[i] for vs in buckets.values()) for i in range(months)]
    delta = max(abs(summed[i] - total[i]) for i in range(months))
    if delta > 1.0:
        raise ValueError(f"grouped leaves do not tie out against {JPM_EXP_ALL} "
                         f"(max monthly gap {delta:,.2f}); buckets refused")
    return {
        "buckets": {k: [round(v, 2) for v in vs] for k, vs in sorted(buckets.items())},
        "other_labels": other,
        "unmapped_accounts": unmapped,
        "below_line_excluded": [],
        "recoverable_tieout_max_gap": round(delta, 4),
        "grouping": "align_tree_via_coa_map",
    }


def _classify(text):
    t = text.lower()
    for bucket, kws in BUCKET_RULES:
        if any(k in t for k in kws):
            return bucket
    return BUCKET_OTHER


def expense_buckets(rows):
    """Monthly expense dollars by bucket from the statement's GL leaf lines.

    A leaf is a coded row with at least one numeric monthly value whose code
    does not end in 98/99 (those are Yardi rollups: 5299, 5499, 3199, 9998,
    9999) and whose label does not start with TOTAL. Section headers (code
    ending -0000, or no numerics) set the section context that classification
    also reads, so "Cleaning-Contract Srvcs" under CLEANING classifies the
    same as a contract line under ADMIN.

    Two regions are walked: recoverable opex (5xxx up to the 5999-9998 total),
    tied out against that total month by month; and other operating expense
    below the NOI line (6xxx and later), excluding financing/non-cash/capital
    sections, which has no statement total of its own and is logged instead.
    """
    import re as _re
    code_re = _re.compile(r"^\d{4}-\d{4}$")
    months = 12
    buckets, other_labels, excluded = {}, [], []
    opex_total = None            # the 5999-9998 row's monthlies
    region = "rev"               # rev -> recoverable -> below
    section = ""
    recoverable_sum = [0.0] * months

    for r in rows:
        code = str(r[0]).strip() if r and r[0] else ""
        label = str(r[1]).strip() if r and len(r) > 1 and r[1] else ""
        if not code_re.match(code):
            continue
        vals = [float(r[c]) if len(r) > c and isinstance(r[c], (int, float))
                else None for c in MONTHS_COLS]
        has_vals = any(v is not None for v in vals)

        if code == "5000-0000":
            region = "recoverable"
        if code == CODE_OPEX:                       # 5999-9998
            opex_total = [v or 0.0 for v in vals]
            region = "below"
            continue
        if region == "rev":
            continue

        is_rollup = code[-2:] in ("98", "99") or label.upper().startswith("TOTAL")
        if is_rollup:
            continue
        if not has_vals:                            # a section header
            if label:
                section = label
            continue

        ctx = f"{section} {label}"
        if region == "below" and any(k in ctx.lower() for k in BELOW_LINE_EXCLUDE):
            excluded.append(label)
            continue

        bucket = _classify(ctx)
        if bucket == BUCKET_OTHER and label not in other_labels:
            other_labels.append(label)
        tgt = buckets.setdefault(bucket, [0.0] * months)
        for i, v in enumerate(vals):
            if v is not None:
                tgt[i] += v
                if region == "recoverable":
                    recoverable_sum[i] += v

    if opex_total is None:
        raise ValueError("no 5999-9998 total row; cannot tie the buckets out")
    delta = max(abs(recoverable_sum[i] - opex_total[i]) for i in range(months))
    if delta > 1.0:
        raise ValueError(f"recoverable leaves do not tie out against 5999-9998 "
                         f"(max monthly gap {delta:,.2f}); buckets refused")

    return {
        "buckets": {k: [round(v, 2) for v in vs] for k, vs in sorted(buckets.items())},
        "other_labels": other_labels,
        "below_line_excluded": excluded,
        "recoverable_tieout_max_gap": round(delta, 4),
    }


def _load_rows(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Report1"]
    return list(ws.iter_rows(values_only=True))


def _property_name(rows):
    # Row 0, col A: e.g. "Palma North (rspalman)"
    cell = rows[0][0] if rows and rows[0] else None
    return str(cell).split("(")[0].strip() if cell else "Unknown Property"


def _property_codes(rows):
    """All property codes the statement covers, first one primary.

    Two title-row shapes exist: "Palma North (rspalman)" for a single code, and
    "Property =  p0005611 p0005612 p0005671 p0005640" when Yardi combines
    several codes into one statement (The Landing reports as four).
    """
    cell = str(rows[0][0]) if rows and rows[0] and rows[0][0] else ""
    if cell.strip().lower().startswith("property") and "=" in cell:
        return [c for c in cell.split("=", 1)[1].split() if c]
    if "(" in cell and ")" in cell:
        return [cell[cell.rfind("(") + 1:cell.rfind(")")].strip()]
    return []


def _property_code(rows):
    codes = _property_codes(rows)
    return codes[0] if codes else None


def _tree(rows):
    """The account tree from the Book row: 'Book = Accrual ; Tree = jpm_bf1'."""
    for r in rows[:6]:
        cell = str(r[0]) if r and r[0] else ""
        if "Tree" in cell and "=" in cell:
            return cell.split("Tree")[1].split("=")[1].strip()
    return None


def _book(rows):
    """Return the accounting book, e.g. 'Accrual' or 'Cash', from the header
    rows (a line like 'Book = Accrual ; Tree = align_resbv')."""
    for r in rows[:6]:
        cell = str(r[0]) if r and r[0] else ""
        if "Book" in cell and "=" in cell:
            part = cell.split("Book")[1].split("=")[1]
            return part.split(";")[0].strip()
    return None


def _month_labels(rows):
    for r in rows:
        if r[2] and "Jul" in str(r[2]) or (r[2] and any(m in str(r[2]) for m in
                ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])):
            # header row: strip the year for compact labels
            labels = []
            for c in MONTHS_COLS:
                v = str(r[c]) if r[c] else ""
                labels.append(v.split()[0] if v else "")
            if all(labels):
                return labels
    return None


def _line_by_code(rows, code):
    """Return the 12 monthly values for a given account code, or None."""
    for r in rows:
        if r[0] and str(r[0]).strip() == code:
            return [float(r[c]) if r[c] is not None else 0.0 for c in MONTHS_COLS]
    return None


def _period_end(rows):
    """Return the last month label in the header, e.g. 'Jun 2026'."""
    for r in rows:
        vals = [str(r[c]) for c in MONTHS_COLS if r[c]]
        if len(vals) == 12 and any(m in vals[0] for m in
                ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]):
            return vals[-1]
    return None


def parse_t12(path):
    rows = _load_rows(path)
    prop = _property_name(rows)
    codes = _property_codes(rows)
    code = codes[0] if codes else None
    labels = _month_labels(rows)
    tree = _tree(rows)
    jpm = bool(tree and tree.lower().startswith("jpm"))
    rev_code = JPM_REVENUE if jpm else CODE_REVENUE
    opex_code = JPM_OPEX if jpm else CODE_OPEX
    rev = _line_by_code(rows, rev_code)
    opex = _line_by_code(rows, opex_code)

    if rev is None:
        raise ValueError(f"Revenue line {rev_code} not found in {path}")
    if opex is None:
        raise ValueError(f"Opex line {opex_code} not found in {path}")

    rev_t12 = sum(rev)
    opex_t12 = sum(opex)
    ratio_t12 = round(100 * opex_t12 / rev_t12, 1) if rev_t12 else None

    monthly = [
        round(100 * opex[k] / rev[k], 1) if rev[k] else None
        for k in range(12)
    ]

    # Statement end period = last month column; used as the rolling-T12 key.
    period_end = _period_end(rows)

    # Bucketed monthly expense detail. A classification failure must not take
    # the ratio store down with it, so it degrades to None with the reason.
    try:
        bucketed = expense_buckets_jpm(rows) if jpm else expense_buckets(rows)
        buckets_error = None
    except (ValueError, OSError) as e:
        bucketed, buckets_error = None, str(e)

    return {
        "property": prop,
        "property_code": code,
        "property_codes": codes,
        "tree": tree,
        "opex_basis": ("jpm 519999-9999 total operating expenses" if jpm
                       else "align 5999-9998 recoverable opex"),
        "book": _book(rows),
        "period_end": period_end,
        "labels": labels,
        "revenue_monthly": [round(x, 2) for x in rev],
        "opex_recoverable_monthly": [round(x, 2) for x in opex],
        "revenue_t12": round(rev_t12, 2),
        "opex_recoverable_t12": round(opex_t12, 2),
        "expense_ratio_t12": ratio_t12,
        "expense_ratio_monthly": monthly,
        "expense_buckets": bucketed,
        "expense_buckets_error": buckets_error,
    }


# Uniform entry point so build_metrics can dispatch every parser the same way.
parse = parse_t12


if __name__ == "__main__":
    out = parse_t12(sys.argv[1])
    print(json.dumps(out, indent=2))
