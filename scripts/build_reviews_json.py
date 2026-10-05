"""Write docs/reviews.json: The Landing's Google reviews, coded by hand.

The Landing tab's "Google reviews" view draws this file. There is no feed behind
it: Google answers the pipeline's network with its "unusual traffic" page, so the
reviews arrive as the Google Maps list copied by hand (newest first) and pasted
in. This script is where that copy is coded -- one row per review, with its
tone, the themes it raises and whether the owner replied -- and docs/reviews.json
is written from it. Never edit the JSON by hand.

    python scripts/build_reviews_json.py

What the copy cannot carry, and the rows therefore do not claim:
  - Star ratings. Google draws them as an icon and copied text leaves it out,
    so tone is read from each review's visible text. No rating is published.
  - Dates. Google shows "3 months ago", so months_ago is read from that and a
    month is approximate. "a year ago" covers anything 12 to 23 months old.
  - The rest of a long review. Google cuts it at a "More" link; those rows are
    text "cut off" and coded from what was visible.

Reviewer names are never recorded, and unit numbers are taken out of excerpts.
A staff member a review praises by name keeps the name; one a review criticises
by name is replaced with their role.

The page computes every count from the rows, so recoding a row here is the
whole refresh. The tallies asserted at the bottom are the ones made by hand
when the rows were first coded; change them deliberately when the rows change.
"""
import datetime
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "reviews.json"
COPIED = datetime.date(2026, 9, 30)

# Order is the order the page lists them in; counts decide nothing about it.
THEMES = [
    ("P1", "problem", "Slow or no response",
     "Management does not answer emails, calls or office visits, or reaches out only after a bad review.",
     "Emails, calls and office visits go unanswered: a renewal after five emails (6), a deposit (17), the final "
     "lease a week before move-in (3), mail forwarding (12), routine email (18). Review 14 says the website, email "
     "and phone are run by AI. Reviews 3 and 6 say management reached out only after a bad review."),
    ("P3", "problem", "Fees, price & value",
     "Charges outside the lease, package or utility charges, rent seen as poor value, management called greedy "
     "or money-first.",
     "Charges outside the lease until challenged (4), $20 package-locker late fees and “shady fees” (23), "
     "rent called “highway robbery” (12) and poor value at $6.5K for a two-bed (18, 10). Management is "
     "called greedy or money-first (3, 4, 15, 26)."),
    ("P4", "problem", "Staff conduct",
     "Staff described as rude, condescending, disorganized, unprofessional or incompetent; staff turnover.",
     "Staff described as rude, condescending, disorganized or unprofessional (3, 8, 15, 17, 20, 31) or "
     "incompetent (3, 4). Review 8 names a staff member as rude. Review 24 points to staff turnover."),
    ("P5", "problem", "Building & amenities",
     "The gym, common areas, social events, alarms, the building's design or a fading community.",
     "A small, busy gym (10, 25), common areas less well kept and the monthly social events dropped (4), alarms "
     "sounding all day (11), and a long-time resident who “saw the life of it get drained away” (12). "
     "Review 24 blames the building's design."),
    ("P2", "problem", "Deposits & move-out",
     "Deposits returned late or not at all, move-out charges such as cleaning or paint, a hard move-out, slow "
     "refunds.",
     "Deposits returned months late or not yet (17, 31), cleaning and repainting charges despite a professional "
     "clean (33), a difficult move-out (20), and a slow refund of a $1,000 application deposit (30)."),
    ("P6", "problem", "Packages & mail",
     "Package lockers and their fees, lost mail, mail forwarding.",
     "Luxer package lockers and their late-pickup fees (23), and a mail room that loses mail and never forwarded "
     "any after move-out (12)."),
    ("H1", "highlight", "Helpful staff",
     "Praise for leasing, management, resident services or maintenance staff, by name or in general.",
     "Tours and the leasing process are praised again and again (16, 19, 22, 27, 32). Lina is named in reviews "
     "19, 21, 22, 27 and 32. Others thank the community manager (16), resident services (21) and a staff member a "
     "vendor worked with (29)."),
    ("H2", "highlight", "Apartments & building",
     "The units, finishes, light, views, appliances, the building itself or its location.",
     "Light-filled units with East Bay views and modern finishes (27), good appliances in a newer building (25), "
     "new units (22) and “very good apartments” (13). Even critical reviews call the building nice "
     "(6, 20)."),
    ("H3", "highlight", "Amenities & community",
     "Common areas, the gym, the conference room, package service, the community feel.",
     "The conference room by the gym (9), the amenities in general (13, 22) and a “great community” "
     "(22)."),
]

# (shown on Google, months ago, edited, text, tone, former resident, about leasing,
#  staff praised by name, themes, owner reply, excerpt, note) -- newest first.
REVIEWS = [
    ("a week ago", 0, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    ("2 weeks ago", 0, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    ("3 weeks ago", 0, False, "full", "Negative", True, True, None, ["P1", "P3", "P4"], "No",
     "Greedy, incompetent, and condescending… when I was moving in I emailed, called, and had someone look for "
     "[the property manager] in her office but got no response… after leaving a negative review I get "
     "contacted by [the property manager] and not when I needed help", "Staff name replaced with role"),
    ("3 weeks ago", 0, False, "full", "Negative", True, False, None, ["P3", "P4", "P5"], "No",
     "the new management is incompetent and greedy. The common areas aren't well kept, they got rid of the "
     "monthly social activities and charge random fees that aren't a part of the lease agreement until you "
     "confront them", None),
    ("a month ago", 1, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    ("a month ago", 1, False, "cut off", "Mixed", False, False, None, ["P1", "H2"], "No",
     "Quite a nice spot to live, I would rate higher but management has not responded to our 5 or so emails about "
     "lease renewal options / negotiation. It seems they respond to bad google reviews though!", "Current resident"),
    ("a month ago", 1, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    ("2 months ago", 2, False, "full", "Negative", False, False, None, ["P4"], "No",
     "[staff member] is so rude and stingy", "Staff name replaced with role; unit number removed"),
    ("2 months ago", 2, False, "full", "Positive", False, False, None, ["H3"], "No",
     "theres a conference room by the gym. took all my meetings here", None),
    ("2 months ago", 2, False, "full", "Negative", False, False, None, ["P3", "P5"], "No",
     "Not worth it - super small gym and nothing worth the price", None),
    ("Edited 2 months ago", 2, True, "cut off", "Negative", False, False, None, ["P5"], "Before edit",
     "Their alarms have been blasting all day. This is probably annoying 10,000 people in the area.",
     "Owner's reply says no lease record was found for the reviewer"),
    ("Edited 2 months ago", 2, True, "full", "Negative", True, False, None, ["P1", "P3", "P5", "P6"], "Before edit",
     "saw the life of it get drained away. They have a mail room that loses your mail, lockers for large packages "
     "that they charge you $ for… rent is absolute highway robbery (even for SF)… they haven't forwarded "
     "a single piece", "Owner's reply answers an earlier, positive version of the review"),
    ("2 months ago", 2, False, "full", "Positive", False, False, None, ["H2", "H3"], "No",
     "Very good apartments and ammenities", None),
    ("3 months ago", 3, False, "cut off", "Negative", True, False, None, ["P1"], "No",
     "The new management SUCKS. Their website, email, and phone are run by AI. No one ever gets back to you. "
     "They're never in the office", "Moved out in May 2026"),
    ("Edited 4 months ago", 4, True, "full", "Negative", False, False, None, ["P3", "P4"], "No",
     "Rude, unprofessional, and only concerned with making money.", None),
    ("4 months ago", 4, False, "full", "Positive", False, True, "Latiffia", ["H1"], "No",
     "The leasing manager was incredibly welcoming. I also got to meet Latiffia… she went above and beyond to "
     "help me and really made my day. Great team!", "Visitor on a tour"),
    ("5 months ago", 5, False, "cut off", "Negative", True, False, None, ["P1", "P2", "P4"], "No",
     "It's been 3 months since we've moved out and no sign of our deposit check. We have contacted building "
     "management repeatedly with zero response. Have never experienced unprofessionalism to this degree", None),
    ("6 months ago", 6, False, "full", "Negative", False, False, None, ["P1", "P3"], "No",
     "doesn't reply to emails. extremely poor customer service, especially when you consider rental for a 2 "
     "bedroom apartment is 6.5K per month.", None),
    ("6 months ago", 6, False, "full", "Positive", False, True, "Lina", ["H1"], "No",
     "Amazing time at The Landing, Lina in particular was incredibly helpful throughout the entire process.", None),
    ("6 months ago", 6, False, "full", "Mixed", True, False, None, ["P2", "P4", "H2"], "No",
     "The building is nice overall but management was not good - rude and disorganized… Move out process was "
     "also very difficult.", None),
    ("7 months ago", 7, False, "full", "Positive", False, False, "Lina", ["H1"], "No",
     "thank the resident service department for helping me locate a missing package… Thank you, Lina for "
     "your support.", None),
    ("7 months ago", 7, False, "full", "Positive", False, True, "Lina", ["H1", "H2", "H3"], "No",
     "Lina and the leasing and management team are the best! Top notch service… this one has a great "
     "community, new units, and amenities.", None),
    ("7 months ago", 7, False, "full", "Negative", False, False, None, ["P3", "P6"], "No",
     "Absolutely trash move with LUXER to manage packaging. $20 for late pick up for a package during holidays "
     "is insane… absurd amount of shady fees.", None),
    ("Edited 7 months ago", 7, True, "cut off", "Mixed", False, False, None, ["P4", "P5"], "Before edit",
     "I truly believe it is the way property was built, there are only so many things a management company can "
     "do. The turnover of staff…", "Owner's reply is three years old"),
    ("8 months ago", 8, False, "cut off", "Mixed", True, False, None, ["P5", "H2"], "Yes",
     "Lived here for 3 years. Nice residence, pretty new building with nice appliances and finishes. The gym is on "
     "the smaller side and gets busy during peak hours",
     "Owner's reply mentions inspection scheduling, deposit accounting and final billing"),
    ("8 months ago", 8, False, "cut off", "Negative", True, False, None, ["P1", "P3"], "Yes",
     "this building has extremely illegal, shady, predatory, and heartbreaking practices. That's what they spend "
     "all their time on instead of responding to residents' needs. They are extremely greedy.",
     "Owner's reply ties it to a lease buy-out clause and reopens the deposit accounting"),
    ("9 months ago", 9, False, "full", "Positive", False, True, "Lina", ["H1", "H2"], "Yes",
     "Beautiful light filled apartment with East Bay views. Lovely modern finishes. Loved the comprehensive "
     "tour—Lena was courteous and friendly", "Written 'Lena'; the owner's reply calls her Lina"),
    ("Edited 10 months ago", 10, True, "cut off", "Unclear", True, False, None, [], "No",
     "Writing a new review. I was a resident this last year (06/24-06/25). There was a change in management "
     "halfway through the year.", "Cut off before giving a view"),
    ("10 months ago", 10, False, "cut off", "Positive", False, False, "Parris", ["H1"], "Yes",
     "I worked with this property as a vendor, and my experience was exceptional. Parris was professional, "
     "engaged, and consistently reliable.", "Vendor, not a resident"),
    ("10 months ago", 10, False, "cut off", "Negative", False, True, None, ["P2"], "Yes",
     "they require a $1000 security deposit for the application… after I cancelled the application, their "
     "return policy…", "Applicant; refund of an application deposit"),
    ("10 months ago", 10, False, "cut off", "Negative", True, False, None, ["P1", "P2", "P4"], "Yes",
     "I moved out in May 2025 and didn't receive any portion of my security deposit until this October, only "
     "after months of fighting this and being ignored. Management was shady, unresponsive, and unprofessional",
     None),
    ("10 months ago", 10, False, "cut off", "Positive", False, True, "Lina", ["H1"], "No",
     "I am not a resident, and I've so far only had a chance to interact with the leasing agent Lina… Lina "
     "is super kind, caring, and diligent.", "Not a resident"),
    ("11 months ago", 11, False, "full", "Negative", True, False, None, ["P2"], "No",
     "They don't return your security deposit and charge hefty cleaning fees and repainting fees even when you "
     "have hired a professional cleaner before leaving", None),
    ("a year ago", 12, False, "cut off", "Mixed", False, False, None, ["P3", "H1", "H2"], "No",
     "Apartments are fairly nice and maintenance staff is responsive… priced and marketed like a luxury "
     "apartment community and that's definitely not the experience.", None),
    ("a year ago", 12, False, "cut off", "Unclear", False, False, None, [], "No",
     "Typical SF apartment rental experience. Positives:…", "Cut off before giving a view"),
    ("a year ago", 12, False, "cut off", "Negative", False, False, None, ["P4"], "Yes",
     "I don't even live in the building and I go to the coffee called Progeny… The way she approached us…",
     "Café visitor, not a resident"),
    ("a year ago", 12, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    ("a year ago", 12, False, "full", "Positive", False, False, None, ["H1"], "Yes", "Great Service", None),
    ("Edited a year ago", 12, True, "cut off", "Positive", False, False, None, ["H1"], "Yes",
     "The current management at The Landing has taken the baton and run with the…", None),
    ("Edited a year ago", 12, True, "none", "No text", False, False, None, [], "Yes", None,
     "Star rating only; the owner's reply thanks them for a 5-star review"),
    ("a year ago", 12, False, "cut off", "Positive", False, False, "Nicholas", ["H1", "H3"], "Yes",
     "Nicholas and the team are doing an amazing job with livening up the community here at The Landing.", None),
    ("a year ago", 12, False, "cut off", "Positive", False, False, None, ["H2"], "Yes",
     "Easily the nicest apartment I've lived in. Top of the line appliances, 10+ ft ceilings, spectacular view.",
     None),
    ("a year ago", 12, False, "full", "Positive", False, False, None, ["H2", "H3"], "Yes",
     "Nice ambiance, close to dogpatch, clean.", None),
    ("a year ago", 12, False, "none", "No text", False, False, None, [], "Yes", None,
     "Star rating only; the owner's reply apologises"),
    ("a year ago", 12, False, "cut off", "Positive", False, False, None, ["H1"], "Yes",
     "I moved in right as the management changed and have had an incredible experience with the new management. "
     "They are extremely helpful, someone is always here even on weekends", None),
    ("a year ago", 12, False, "cut off", "Negative", True, False, None, ["P1", "P2"], "Yes",
     "New management is not better than the old one. Poor communication during the management change. Move out "
     "experience is terrible… Wall paint charge is overpriced", None),
    ("a year ago", 12, False, "cut off", "Mixed", False, False, None, ["P3"], "Yes",
     "Overall has been a nice experience. Major flaw is the utilities… we have been charged anywhere from "
     "$80-$175 for WATER ALONE on some months.", None),
    ("a year ago", 12, False, "full", "Positive", False, True, "Marissa", ["H1"], "Yes",
     "Marissa was awesome!! She explained everything in the showing and process.", None),
    ("a year ago", 12, False, "cut off", "Negative", True, False, None, ["P2"], "Yes",
     "Do yourself a favor and avoid this place at all costs! I had a terrible experience with this apartment "
     "complex. They didn't return my…",
     "Deposit theme and move-out taken from the owner's reply, which dates the move-out before the current "
     "management"),
    ("a year ago", 12, False, "cut off", "Negative", False, False, None, ["P3", "P5"], "Yes",
     "It's stupidly overpriced and poorly designed. The building has like 0 signs… The game room is terrible "
     "for hosting", None),
    ("a year ago", 12, False, "cut off", "Mixed", True, False, None, ["H3"], "Yes",
     "Great common area spaces and great for hosting. Gym is well equipped. Package service is great… "
     "Apartment itself was pretty average.", None),
    ("Edited a year ago", 12, True, "cut off", "Negative", False, False, None, ["P4", "P5"], "Yes",
     "Do not rent here. We moved in thinking it was going to be a great; fun amenities, nice people, friendly "
     "staff etc... It was the opposite.", None),
    ("a year ago", 12, False, "none", "No text", False, False, None, [], "Yes", None,
     "Star rating only; the owner's reply notes it had no text"),
]

WATCH = [
    "Review 26 (about Jan 2026) calls the building's practices \u201cillegal, shady, predatory\u201d. The owner's "
    "reply ties it to a lease buy-out clause.",
    "Review 12 praised the building a year ago (the owner's reply thanks them for it) and has since been edited to "
    "a negative review.",
]

# The Bottom Line card's two columns. Each point names the theme whose count the
# page prints before it ("7 of 33 reviews this year"), so no count is typed here;
# "metric": "replies" prints the owner's reply rate instead. "former" adds how many
# of those reviews came from people who have moved out. Findings cite review
# numbers, and "do" is the suggested next step.
ASSESSMENT = {
    "strengths": [
        {"theme": "H1", "lead": "Leasing and tours",
         "finding": "Tours and the leasing process draw more praise than anything else here (16, 19, 22, 27, 32), "
                    "and Lina is named again and again (19, 21, 22, 27, 32).",
         "do": "Make the way Lina runs a tour the standard for the whole team, and carry that attention past "
               "move-in, which is where the reviews turn."},
        {"theme": "H2", "lead": "The apartments themselves",
         "finding": "Light, East Bay views, modern finishes and appliances are praised (13, 22, 25, 27), and even "
                    "critical reviewers call the building nice (6, 20). The complaints are about service, not the "
                    "product.",
         "do": "Lead tours and marketing with the views, light and finishes, and close the service gaps that make "
               "residents say it isn't worth the price (10, 18)."},
        {"theme": "H3", "lead": "Amenities and community spaces",
         "finding": "Residents use and like the conference room by the gym (9), the amenities in general (13, 22) "
                    "and the community feel (22).",
         "do": "Promote the conference room to residents who work from home, and bring back the monthly social "
               "events one reviewer says were dropped (4)."},
    ],
    "improvements": [
        {"theme": "P1", "lead": "Responsiveness",
         "finding": "The most common complaint: emails, calls and office visits that go unanswered, including a "
                    "renewal negotiation after five emails (6), a deposit (17) and a final lease a week before "
                    "move-in (3). One reviewer says the website, email and phone are run by AI and no one gets "
                    "back (14).",
         "do": "Set a response standard, such as every email and call answered within one business day; check that "
               "questions the AI assistant can't answer reach a person; and send renewal questions straight to "
               "leasing, since an unanswered renewal is revenue at risk."},
        {"metric": "replies", "lead": "Public replies to reviews",
         "finding": "Public replies stopped around January 2026, and two reviewers say management reached out "
                    "privately only after a bad review (3, 6), which reads as caring about the rating rather than "
                    "the resident.",
         "do": "Reply publicly to every review, newest first and within a couple of days, answering what the "
               "review actually says, and follow up privately as well, not instead."},
        {"theme": "P2", "former": True, "lead": "Move-out and deposits",
         "finding": "Deposits returned months late or not yet (17, 31), cleaning and repaint charges despite a "
                    "professional clean (33), and a hard move-out (20). These come from people who have already "
                    "left, and their reviews stay up.",
         "do": "Audit the process against California's 21-day deadline for returning a deposit or an itemized "
               "statement (Civil Code \u00a71950.5), offer a walkthrough before move-out so charges are not a "
               "surprise, and pay refunds by ACH, as the owner's reply to review 31 already promised."},
        {"theme": "P3", "lead": "Fees and value",
         "finding": "Charges outside the lease until challenged (4), $20 package-locker late fees and \u201cshady "
                    "fees\u201d (23), and rent seen as poor value for the service (10, 12, 18). Greedy is the word "
                    "several reviewers reach for (3, 4, 26).",
         "do": "Give every resident a one-page fee schedule at signing, audit the charges reviewers say were not "
               "in the lease, and lengthen or waive the package-locker late-fee window around holidays."},
        {"theme": "P4", "lead": "Staff conduct",
         "finding": "Staff described as rude, condescending, disorganized or unprofessional (3, 8, 15, 17, 20, 31), "
                    "with staff turnover noted (24). The same building earns praise for its leasing team, so the "
                    "gap is consistency.",
         "do": "Coach the on-site team on resident service, follow up on review 8 internally, and hand residents "
               "over properly when staff change."},
        {"theme": "P5", "lead": "Building and community upkeep",
         "finding": "A small, busy gym (10, 25), common areas less well kept and social events dropped (4), and "
                    "alarms sounding all day (11).",
         "do": "Bring back the monthly events, look at the gym at peak hours, and give residents advance notice of "
               "alarm tests."},
    ],
}

TONES = ("Positive", "Mixed", "Negative", "Unclear", "No text")
TEXTS = ("full", "cut off", "none")
REPLIES = ("Yes", "Before edit", "No")


def month_back(n):
    y, m = COPIED.year, COPIED.month - n
    while m < 1:
        m += 12
        y -= 1
    return datetime.date(y, m, 1)


def span(newest, oldest):
    a, b = month_back(oldest), month_back(newest)
    if a.year == b.year:
        return f"{a:%b}–{b:%b %Y}"
    return f"{a:%b %Y}–{b:%b %Y}"


def build():
    codes = [t[0] for t in THEMES]
    reviews = []
    for i, r in enumerate(REVIEWS, 1):
        shown, months, edited, text, tone, former, leasing, staff, themes, reply, excerpt, note = r
        assert tone in TONES and text in TEXTS and reply in REPLIES, (i, tone, text, reply)
        assert set(themes) <= set(codes), (i, themes)
        assert (text == "none") == (tone == "No text") == (excerpt is None), i
        reviews.append({
            "n": i, "shown": shown, "months_ago": months, "edited": edited, "text": text, "tone": tone,
            "former_resident": former, "about_leasing": leasing, "staff_praised": staff,
            "themes": [c for c in codes if c in themes], "owner_reply": reply, "excerpt": excerpt, "note": note,
        })

    # The tallies made by hand when the rows were first coded (2026-10-01),
    # so a slip in a row cannot change the published view unnoticed.
    year = [r for r in reviews if r["months_ago"] < 12]
    old = [r for r in reviews if r["months_ago"] >= 12]
    count = lambda rows, code: sum(code in r["themes"] for r in rows)
    assert (len(reviews), len(year), len(old)) == (53, 33, 20)
    assert {c: (count(year, c), count(old, c)) for c in codes} == {
        "P1": (8, 1), "P3": (8, 3), "P4": (8, 2), "P5": (6, 2), "P2": (5, 2), "P6": (2, 0),
        "H1": (7, 6), "H2": (6, 3), "H3": (3, 3)}
    assert [sum(r["tone"] == "Negative" for r in rows) for rows in (year, old)] == [15, 5]
    assert [sum(r["owner_reply"] == "Yes" for r in rows) for rows in (year, old)] == [6, 17]

    for side in ("strengths", "improvements"):
        for item in ASSESSMENT[side]:
            assert item.get("theme") in codes or item.get("metric") == "replies", item["lead"]
            assert item["lead"] and item["finding"] and item["do"], item["lead"]

    return {
        "_comment": "Written by scripts/build_reviews_json.py, which holds the hand coding. Never edit by hand.",
        "property": "the-landing",
        "building": "The Landing",
        "address": "1395 22nd Street, San Francisco 94107",
        "source": "Google Maps review list, newest first, copied by hand",
        "copied": COPIED.isoformat(),
        "star_ratings": False,
        "periods": [
            {"key": "old", "label": "12+ months ago", "min": 12, "max": None},
            {"key": "prior", "label": span(6, 11), "min": 6, "max": 11},
            {"key": "recent", "label": span(0, 5), "min": 0, "max": 5},
        ],
        "themes": [{"code": c, "kind": k, "label": lab, "definition": d, "says": s} for c, k, lab, d, s in THEMES],
        "reviews": reviews,
        "watch": WATCH,
        "assessment": ASSESSMENT,
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parent.parent)}: {len(data['reviews'])} reviews, "
          f"periods {', '.join(p['label'] for p in data['periods'])}")
