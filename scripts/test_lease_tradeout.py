"""
test_lease_tradeout.py
----------------------
Checks for the Yardi Lease Tradeout Report parser and its store.

Fixture-free: every workbook is built in a temp dir, so nothing here needs the
real export (which is gitignored like every other raw report) and nothing
touches the network.

The checks that matter are the invisible failures — the ones that publish a
number rather than an error:

  * the two-row header, where `Gross Rent`/`Conc`/`Eff Rent`/`Term` appear once
    under Current Lease and again under Previous Lease. Matching the column row
    alone swaps the two sides and inverts every trade-out, and the totals still
    tie out against a file built the same wrong way.
  * `(2.5%)` — a negative percentage, parenthesised with the sign marker
    outside the percent sign. A pattern that expects `)` before `%` drops 42 of
    The Landing's 247 leases silently and averages only the positive ones.
  * a `.XLS` file that is really an `.xlsx`, which is what Yardi writes.
  * the Grand Total tie-out, which is the only thing standing between a dropped
    floor-plan section and an understated building.
  * Subtotal/Average/Total rows read as leases, which would add a 1,458-month
    lease to the series.

Run: python scripts/test_lease_tradeout.py
"""
import os
import shutil
import sys
import tempfile

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_lease_tradeout import (parse, summarise, window,  # noqa: E402
                                  _num, _pct)
from xlsx_anchors import LayoutError  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))


GROUPS = ["Unit Details", "", "", "", "", "Current Lease", "", "", "", "", "", "",
          "", "", "", "", "", "", "Previous Lease", "", "", "", "", "", "", "", "",
          "", "Vacant Days", "Term Variance", "Trade Out %", "Trade Out $"]
COLS = ["Unit Type", "Building", "", "Unit", "Sq Ft", "Rate Type", "Lease Type",
        "App Signed Date", "Lease Start", "Lease\nEnd", "Term", "Prem", "",
        "Gross Rent", "Conc", "", "Eff Rent", "", "Rate Type", "", "Lease Start",
        "Scheduled\nLease End", "Actual\nLease End", "Term", "Prem", "Gross Rent",
        "Conc", "Eff Rent", "", "", "", ""]


def lease_row(unit, signed, eff, prev_eff, prev_start="6/7/23", conc=0,
              prev_conc=0, plan="laa5"):
    """One lease row in the real column layout."""
    r = [""] * 32
    r[0], r[1], r[3], r[4] = plan, "N/A", unit, 688
    r[5], r[6], r[7], r[8] = "New", "CON", signed, signed
    r[9], r[10], r[11] = "6/7/26", 13.0, "$55"
    r[13], r[14], r[16] = f"${eff + conc:,.0f}", f"${conc:,.0f}", f"${eff:,.0f}"
    r[18], r[20], r[21], r[22] = "N", prev_start, "9/6/24", "4/30/25"
    r[23], r[24] = 15.0, "$55"
    r[25], r[26], r[27] = f"${prev_eff + prev_conc:,.0f}", f"${prev_conc:,.0f}", f"${prev_eff:,.0f}"
    r[28], r[29] = 8.0, "0"
    pct = (eff / prev_eff - 1) * 100 if prev_eff else 0
    r[30] = f"({abs(pct):.1f}%)" if pct < 0 else f"{pct:.1f}%"
    amt = eff - prev_eff
    r[31] = f"-${abs(amt):,.0f}" if amt < 0 else f"${amt:,.0f}"
    return r


def build(path, leases, grand=None, period="From: 8/1/24 To: 9/16/26",
          with_grand=True, subtotals=True):
    """Write a report with the real header shape. `grand` overrides the totals."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LeaseTradeoutReport"
    ws.append([])
    ws.append(["Lease Tradeout Report"])
    ws.append([period])
    ws.append([])
    ws.append(["Desired Rate Type: NEW  Lease Date: App Date/Signed Date"])
    ws.append(["Calculate Tradeout on: Effective Rent"])
    ws.append(["Sep 17, 2026, 2:38:27 PM"])
    ws.append(GROUPS)
    ws.append(COLS)
    ws.append([])
    ws.append(["The Landing Property Owner LLC"])
    ws.append(["Floor Plan:", "", "1B1B-1B1BD*"])
    ws.append([])
    for r in leases:
        ws.append(r)
    cur = sum(_num(r[16]) for r in leases)
    prev = sum(_num(r[27]) for r in leases)
    if subtotals:
        sub = [""] * 32
        sub[0] = "Subtotal:"
        sub[10], sub[16], sub[27] = 1458.0, f"${cur:,.0f}", f"${prev:,.0f}"
        sub[31] = f"${cur - prev:,.0f}"
        ws.append(sub)
        avg = [""] * 32
        avg[0] = "Average:"
        avg[16] = f"${cur / max(len(leases), 1):,.0f}"
        ws.append(avg)
    if with_grand:
        g = [""] * 32
        g[0] = "Grand Total:"
        c, p = grand or (cur, prev)
        g[16], g[27], g[31] = f"${c:,.0f}", f"${p:,.0f}", f"${c - p:,.0f}"
        ws.append(g)
    wb.save(path)
    return path


def as_xls(path):
    """The same bytes under a .XLS name — what Yardi actually writes."""
    out = path[:-5] + ".XLS"
    shutil.copy(path, out)
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="tradeout-")
    x = lambda n: os.path.join(tmp, n)  # noqa: E731

    print("\n1. the number parser")
    check("$4,226 reads as 4226", _num("$4,226") == 4226.0)
    check("(2.5%) is NEGATIVE two and a half percent", _pct("(2.5%)") == -0.025,
          f"got {_pct('(2.5%)')}")
    check("35.0% reads as 0.35", _pct("35.0%") == 0.35)
    check("-$78 reads as -78", _num("-$78") == -78.0)
    check("a real float passes through", _num(4226.0) == 4226.0)
    check("an empty cell is None", _num("") is None and _num(None) is None)
    check("a word is None, not 0", _num("Subtotal:") is None)

    print("\n2. a .XLS that is really an .xlsx")
    p = build(x("a.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)])
    r = parse(as_xls(p))
    check("opens by content, not extension", len(r["leases"]) == 1)
    with open(x("old.XLS"), "wb") as fh:
        fh.write(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    try:
        parse(x("old.XLS"))
        check("a genuine legacy .xls is named as such", False, "no error raised")
    except LayoutError as e:
        check("a genuine legacy .xls is named as such", "legacy" in str(e).lower())

    print("\n3. the two-row header keeps Current and Previous apart")
    p = build(x("b.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)])
    r = parse(p)
    l0 = r["leases"][0]
    check("current effective rent is the current one", l0["eff_rent"] == 4226.0,
          f"got {l0['eff_rent']}")
    check("previous effective rent is the previous one", l0["prev_eff_rent"] == 3131.0,
          f"got {l0['prev_eff_rent']}")
    check("the trade-out is positive, not inverted", l0["tradeout_pct"] > 0)

    print("\n4. totals rows are never read as leases")
    p = build(x("c.xlsx"), [lease_row("102", "5/8/25", 4226, 3131),
                            lease_row("103", "6/3/25", 3568, 3399)])
    r = parse(p)
    check("two leases, not four", len(r["leases"]) == 2, f"got {len(r['leases'])}")
    check("no lease carries the subtotal's 1,458-month term",
          all((l["term"] or 0) < 100 for l in r["leases"]))

    print("\n5. the Grand Total tie-out")
    p = build(x("d.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)],
              grand=(9999, 3131))
    try:
        parse(p)
        check("a file that misses its own total is refused", False, "published anyway")
    except LayoutError as e:
        check("a file that misses its own total is refused", "Grand" in str(e) or "refusing" in str(e))
    p = build(x("e.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)], with_grand=False)
    try:
        parse(p)
        check("a file with no Grand Total row is refused", False, "published anyway")
    except LayoutError:
        check("a file with no Grand Total row is refused", True)
    p = build(x("f.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)])
    r = parse(p)
    check("a file that ties out reports its checks",
          len(r["checks"]) == 3 and all(abs(c["diff"]) < 0.01 for c in r["checks"]))

    print("\n6. weighted is not the mean")
    # one ordinary lease and one whose previous rent was gutted by a concession
    ls = [lease_row("102", "5/8/25", 4400, 4000),
          lease_row("265", "11/30/24", 5363, 86, prev_conc=62716)]
    p = build(x("g.xlsx"), ls)
    t = parse(p)["totals"]
    check("weighted uses total over total",
          abs(t["pct"] - ((4400 + 5363) / (4000 + 86) - 1)) < 1e-6, f"got {t['pct']}")
    check("the mean is far higher and is kept separate", t["mean_pct"] > t["pct"] * 5,
          f"weighted {t['pct']:.2f} mean {t['mean_pct']:.2f}")
    check("the concession lease alone would read in the thousands of percent",
          t["mean_pct"] > 25)

    print("\n7. the period and the report's own settings")
    r = parse(build(x("h.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)]))
    check("period read from the From/To row",
          r["period_start"] == "2024-08-01" and r["period_end"] == "2026-09-16")
    check("rate type read", r["rate_type"] == "NEW")
    check("tradeout basis read", r["tradeout_basis"] == "Effective Rent")
    check("lease date basis read", r["lease_date_basis"] == "App Date/Signed Date")
    try:
        parse(build(x("i.xlsx"), [lease_row("102", "5/8/25", 4226, 3131)], period="(no dates here)"))
        check("a file with no period is refused", False, "published anyway")
    except LayoutError:
        check("a file with no period is refused", True)

    print("\n8. leases are dated by the signed date, and grouped by it")
    ls = [lease_row("102", "1/15/26", 4400, 4000),
          lease_row("103", "2/20/26", 4400, 4000),
          lease_row("104", "2/25/26", 4400, 4000)]
    t = summarise(parse(build(x("j.xlsx"), ls))["leases"])
    check("one bucket per signed month", [m["month"] for m in t["months"]] == ["2026-01", "2026-02"])
    check("February holds two", t["months"][1]["leases"] == 2)

    print("\n9. the trailing window")
    ls = [lease_row("1", "1/15/26", 4400, 4000), lease_row("2", "2/15/26", 4400, 4000),
          lease_row("3", "3/15/26", 4400, 4000), lease_row("4", "4/15/26", 5000, 4000)]
    leases = parse(build(x("k.xlsx"), ls))["leases"]
    w = window(leases, 3)
    check("T3 is the last three CALENDAR months, not the last three leases",
          w["window_start"] == "2026-02" and w["window_end"] == "2026-04")
    check("T3 holds three of the four leases", w["leases"] == 3)
    check("a window longer than the file is marked incomplete",
          window(leases, 24)["complete"] is False)
    check("a window inside the file is complete", w["complete"] is True)
    check("window(0 leases) is None", window([], 3) is None)

    print("\n10. the store accumulates by lease")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_metrics as bm
    old_data = bm.DATA
    try:
        bm.DATA = __import__("pathlib").Path(tmp) / "data"
        prop = {"slug": "t", "name": "T"}
        a = parse(build(x("m1.xlsx"), [lease_row("102", "5/8/25", 4226, 3131),
                                       lease_row("103", "6/3/25", 3568, 3399)]))
        a["source_file"] = "file-a.XLS"
        bm.store_lease_tradeout(prop, a)
        b = parse(build(x("m2.xlsx"), [lease_row("104", "7/9/26", 5000, 4000)]))
        b["source_file"] = "file-b.XLS"
        bm.store_lease_tradeout(prop, b)
        import json
        held = json.load(open(bm.DATA / "t" / "lease_tradeout.json"))
        check("a second file adds rather than replaces", len(held["leases"]) == 3,
              f"got {len(held['leases'])}")
        check("both files are recorded", len(held["files"]) == 2)
        # re-file the first one: same leases, must not double
        bm.store_lease_tradeout(prop, a)
        held = json.load(open(bm.DATA / "t" / "lease_tradeout.json"))
        check("re-filing a window replaces its leases", len(held["leases"]) == 3,
              f"got {len(held['leases'])}")
        check("re-filing does not add a second file record", len(held["files"]) == 2)
        # a unit that turns over twice inside one window is two leases
        c = parse(build(x("m3.xlsx"), [
            lease_row("500", "5/8/25", 4226, 3131, prev_start="6/7/23"),
            lease_row("500", "6/21/26", 5429, 4226, prev_start="5/8/25")]))
        c["source_file"] = "file-c.XLS"
        bm.store_lease_tradeout(prop, c)
        held = json.load(open(bm.DATA / "t" / "lease_tradeout.json"))
        check("one unit turning over twice is two leases, not one",
              sum(1 for l in held["leases"] if l["unit"] == "500") == 2)
        check("no resident-shaped key survives the store",
              not any(k in l for l in held["leases"]
                      for k in ("resident", "resident_name", "tenant", "name")))
    finally:
        bm.DATA = old_data

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
