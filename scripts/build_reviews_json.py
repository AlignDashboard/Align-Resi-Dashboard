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

A review keeps its number from copy to copy. A new one takes the next number,
and one Google no longer lists leaves its number unused, so a finding that
cites "review 26" means the same review after every refresh. The rows are kept
in the copy's own newest-first order, which is the order the page lists them.

To refresh from a new copy: set COPIED, recode the rows against the paste
(Google's relative dates move, edits re-date a review, replies appear), give
new reviews the next numbers, and run this. Each run stores its copy under
data/the-landing/reviews/<copied>.json, and the next copy is compared against
the newest one stored before it: what is new, edited, gone, newly answered or
recoded is published as `changes`, with the earlier copy's rows as `previous`,
so the page can say what moved without a typed count.

The page computes every count from the rows, so recoding a row here is the
whole refresh. The tallies asserted at the bottom are the ones made by hand for
the current copy; change them deliberately when the rows change.
"""
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "reviews.json"
SNAPSHOTS = ROOT / "data" / "the-landing" / "reviews"
COPIED = datetime.date(2026, 10, 19)

# The 19 Oct paste stops before these, the sixteen oldest: they are carried from
# the copy they were last seen in, as coded then, and build() checks that.
CARRIED = set(range(38, 54))

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
     "Charges outside the lease until challenged (4), package-locker charges for residents who are away (12), "
     "rent called “highway robbery” (12) and poor value at $6.5K for a two-bed (18, 10). Management is "
     "called greedy or money-first (3, 4, 15, 26)."),
    ("P4", "problem", "Staff conduct",
     "Staff described as rude, condescending, disorganized, unprofessional or incompetent; staff turnover.",
     "Staff described as rude, condescending, disorganized or unprofessional (3, 8, 15, 17, 20, 31) or "
     "incompetent (3, 4, 55). Review 8 names a staff member as rude, and the owner's reply to review 14 answers "
     "concerns about interactions with the team. Reviews 22 and 24 point to staff turnover."),
    ("P5", "problem", "Building & amenities",
     "The gym, common areas, social events, alarms, the building's design or a fading community.",
     "A small, busy gym (10, 25), common areas less well kept and the monthly social events dropped (4), alarms "
     "sounding all day (11), the elevators and BBQ grills, according to the owner's reply (6), and a long-time "
     "resident who “saw the life of it get drained away” (12). Review 24 blames the building's design."),
    ("P2", "problem", "Deposits & move-out",
     "Deposits returned late or not at all, move-out charges such as cleaning or paint, a hard move-out, slow "
     "refunds.",
     "A refund of nearly $6,000 still unpaid nine months after a January move-out (54, 55), deposits returned "
     "months late or not yet (17, 31), cleaning and repainting charges despite a professional clean (33), a "
     "difficult move-out (20), and a slow refund of a $1,000 application deposit (30)."),
    ("P6", "problem", "Packages & mail",
     "Package lockers and their fees, lost mail, mail forwarding.",
     "A mail room that loses mail, package lockers that charge residents who are away, and no mail forwarded "
     "after move-out (12)."),
    ("H1", "highlight", "Helpful staff",
     "Praise for leasing, management, resident services or maintenance staff, by name or in general.",
     "Tours and the leasing process are praised again and again (16, 19, 27, 32, 58). Lina is named in reviews "
     "19, 21, 22, 27 and 32. Others thank the community manager (16, 58), resident services (21) and a staff "
     "member a vendor worked with (29)."),
    ("H2", "highlight", "Apartments & building",
     "The units, finishes, light, views, appliances, the building itself or its location.",
     "Light-filled units with East Bay views and modern finishes (27), good appliances in a newer building (25), "
     "a building and units still well maintained after six years (57) and “very good apartments” (13). "
     "Even critical reviews call the building nice (6, 20)."),
    ("H3", "highlight", "Amenities & community",
     "Common areas, the gym, the conference room, package service, the community feel.",
     "The conference room by the gym (9) and the amenities in general (13)."),
]

# (review number, shown on Google, months ago, edited, text, tone, former
#  resident, about leasing, staff praised by name, themes, owner reply, excerpt,
#  note) -- in the copy's newest-first order.
REVIEWS = [
    (54, "a week ago", 0, False, "cut off", "Negative", True, False, None, ["P2"], "Yes",
     "The Landing has made getting our security deposit back an absolute nightmare. We moved out in January 2026. "
     "It is October, and the nearly $6,000 refund they calculated is still unpaid, even though our lease says the "
     "refund was due within 21…",
     "Moved out in January 2026; the owner's reply says the account and the earlier refund checks are being reviewed"),
    (55, "a week ago", 0, False, "cut off", "Negative", True, False, None, ["P2", "P4"], "Yes",
     "Literally never live here. To be more specific, they will steal your deposit and never give it back. Do not "
     "live at The Landing if you expect competent management or to get your…",
     "Same household as review 54, per the owner's replies, which mention refund checks that could not be deposited"),
    (56, "a week ago", 0, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    (57, "a week ago", 0, False, "cut off", "Positive", True, False, None, ["H2"], "No",
     "Lived there since 2020 and lived across 3 different units and really loved my time there. The property is "
     "beautiful and the building and units are very well maintained even after all these years. It's very dog "
     "friendly and the staff is very…",
     "Lived there from 2020, across three units; cut off as it turns to the staff"),
    (22, "Edited a week ago", 0, True, "cut off", "Mixed", False, False, "Lina", ["P4", "H1"], "Before edit",
     "Updating my review: While Lina is an awesome member of the team. This place has gone through 3…",
     "Rewritten since Sep 30, when it praised the leasing team; cut off after “gone through 3”, coded as turnover. "
     "Its reply answers the earlier version, in the words of the reply to review 21"),
    (58, "2 weeks ago", 0, False, "full", "Positive", False, True, None, ["H1"], "Yes",
     "Had a tour & was very impressed ! The community manager was super helpful. She was extremely knowledgable on "
     "the property and amenities. 10/10!",
     "Visitor on a tour"),
    (11, "Edited 2 weeks ago", 0, True, "cut off", "Negative", False, False, None, ["P5"], "Before edit",
     "Their alarms have been blasting all day. This is probably annoying 10,000 people in the area.",
     "Edited again since Sep 30. The owner's reply, from a year ago, says no lease record was found for the reviewer"),
    (1, "3 weeks ago", 0, False, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply thanks them for a 5-star review"),
    (2, "a month ago", 1, False, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply thanks them for a 4-star review"),
    (3, "a month ago", 1, False, "full", "Negative", True, True, None, ["P1", "P3", "P4"], "Yes",
     "Greedy, incompetent, and condescending… when I was moving in I emailed, called, and had someone look for [the "
     "property manager] in her office but got no response… after leaving a negative review I get contacted by [the "
     "property manager] and not when I needed help",
     "Staff name replaced with role"),
    (4, "a month ago", 1, False, "full", "Negative", True, False, None, ["P3", "P4", "P5"], "Yes",
     "the new management is incompetent and greedy. The common areas aren't well kept, they got rid of the monthly "
     "social activities and charge random fees that aren't a part of the lease agreement until you confront them",
     None),
    (5, "a month ago", 1, False, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply thanks them for a 4-star review"),
    (6, "2 months ago", 2, False, "cut off", "Mixed", False, False, None, ["P1", "P5", "H2"], "Yes",
     "Quite a nice spot to live, I would rate higher but management has not responded to our 5 or so emails about "
     "lease renewal options / negotiation. It seems they respond to bad google reviews though!",
     "Current resident, since renewed. The owner's reply answers comments on the elevators, BBQ grills and common "
     "areas that the copy cuts off, so the building theme is taken from it"),
    (7, "2 months ago", 2, False, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply apologises"),
    (8, "2 months ago", 2, False, "full", "Negative", False, False, None, ["P4"], "Yes",
     "[staff member] is so rude and stingy",
     "Staff name replaced with role; unit number removed"),
    (9, "2 months ago", 2, False, "full", "Positive", False, False, None, ["H3"], "Yes",
     "theres a conference room by the gym. took all my meetings here",
     None),
    (10, "3 months ago", 3, False, "full", "Negative", False, False, None, ["P3", "P5"], "Yes",
     "Not worth it - super small gym and nothing worth the price",
     None),
    (12, "Edited 3 months ago", 3, True, "full", "Negative", True, False, None, ["P1", "P3", "P5", "P6"], "Before edit",
     "saw the life of it get drained away. They have a mail room that loses your mail, lockers for large packages "
     "that they charge you $ for… rent is absolute highway robbery (even for SF)… they haven't forwarded a single "
     "piece",
     "Owner's reply answers an earlier, positive version of the review"),
    (13, "3 months ago", 3, False, "full", "Positive", False, False, None, ["H2", "H3"], "Yes",
     "Very good apartments and ammenities",
     None),
    (14, "4 months ago", 4, False, "cut off", "Negative", True, False, None, ["P1", "P4"], "Yes",
     "The new management SUCKS. Their website, email, and phone are run by AI. No one ever gets back to you. "
     "They're never in the office",
     "Moved out in May 2026. The owner's reply answers concerns about interactions with the team, so the staff "
     "theme is taken from it"),
    (15, "Edited 4 months ago", 4, True, "full", "Negative", False, False, None, ["P3", "P4"], "Yes",
     "Rude, unprofessional, and only concerned with making money.",
     None),
    (16, "4 months ago", 4, False, "full", "Positive", False, True, "Latiffia", ["H1"], "Yes",
     "The leasing manager was incredibly welcoming. I also got to meet Latiffia… she went above and beyond to help "
     "me and really made my day. Great team!",
     "Visitor on a tour"),
    (17, "5 months ago", 5, False, "cut off", "Negative", True, False, None, ["P1", "P2", "P4"], "Yes",
     "It's been 3 months since we've moved out and no sign of our deposit check. We have contacted building "
     "management repeatedly with zero response. Have never experienced unprofessionalism to this degree",
     None),
    (18, "7 months ago", 7, False, "full", "Negative", False, False, None, ["P1", "P3"], "Yes",
     "doesn't reply to emails. extremely poor customer service, especially when you consider rental for a 2 bedroom "
     "apartment is 6.5K per month.",
     None),
    (19, "7 months ago", 7, False, "full", "Positive", False, True, "Lina", ["H1"], "Yes",
     "Amazing time at The Landing, Lina in particular was incredibly helpful throughout the entire process.",
     None),
    (20, "7 months ago", 7, False, "full", "Mixed", True, False, None, ["P2", "P4", "H2"], "Yes",
     "The building is nice overall but management was not good - rude and disorganized… Move out process was also "
     "very difficult.",
     None),
    (21, "8 months ago", 8, False, "full", "Positive", False, False, "Lina", ["H1"], "Yes",
     "thank the resident service department for helping me locate a missing package… Thank you, Lina for your "
     "support.",
     None),
    (24, "Edited 8 months ago", 8, True, "cut off", "Mixed", False, False, None, ["P4", "P5"], "Before edit",
     "I truly believe it is the way property was built, there are only so many things a management company can do. "
     "The turnover of staff…",
     "Owner's reply is three years old"),
    (25, "9 months ago", 9, False, "cut off", "Mixed", True, False, None, ["P5", "H2"], "Yes",
     "Lived here for 3 years. Nice residence, pretty new building with nice appliances and finishes. The gym is on "
     "the smaller side and gets busy during peak hours",
     "Owner's reply mentions inspection scheduling, deposit accounting and final billing"),
    (26, "9 months ago", 9, False, "cut off", "Negative", True, False, None, ["P1", "P3"], "Yes",
     "this building has extremely illegal, shady, predatory, and heartbreaking practices. That's what they spend "
     "all their time on instead of responding to residents' needs. They are extremely greedy.",
     "Owner's reply ties it to a lease buy-out clause and reopens the deposit accounting"),
    (27, "10 months ago", 10, False, "full", "Positive", False, True, "Lina", ["H1", "H2"], "Yes",
     "Beautiful light filled apartment with East Bay views. Lovely modern finishes. Loved the comprehensive "
     "tour—Lena was courteous and friendly",
     "Written 'Lena'; the owner's reply calls her Lina"),
    (28, "Edited 10 months ago", 10, True, "cut off", "Unclear", True, False, None, [], "No",
     "Writing a new review. I was a resident this last year (06/24-06/25). There was a change in management halfway "
     "through the year.",
     "Cut off before giving a view"),
    (29, "11 months ago", 11, False, "cut off", "Positive", False, False, "Parris", ["H1"], "Yes",
     "I worked with this property as a vendor, and my experience was exceptional. Parris was professional, engaged, "
     "and consistently reliable.",
     "Vendor, not a resident"),
    (30, "11 months ago", 11, False, "cut off", "Negative", False, True, None, ["P2"], "Yes",
     "they require a $1000 security deposit for the application… after I cancelled the application, their return "
     "policy…",
     "Applicant; refund of an application deposit"),
    (31, "11 months ago", 11, False, "cut off", "Negative", True, False, None, ["P1", "P2", "P4"], "Yes",
     "I moved out in May 2025 and didn't receive any portion of my security deposit until this October, only after "
     "months of fighting this and being ignored. Management was shady, unresponsive, and unprofessional",
     None),
    (32, "11 months ago", 11, False, "cut off", "Positive", False, True, "Lina", ["H1"], "No",
     "I am not a resident, and I've so far only had a chance to interact with the leasing agent Lina… Lina is super "
     "kind, caring, and diligent.",
     "Not a resident"),
    (33, "a year ago", 12, False, "full", "Negative", True, False, None, ["P2"], "No",
     "They don't return your security deposit and charge hefty cleaning fees and repainting fees even when you have "
     "hired a professional cleaner before leaving",
     None),
    (34, "a year ago", 12, False, "cut off", "Mixed", False, False, None, ["P3", "H1", "H2"], "No",
     "Apartments are fairly nice and maintenance staff is responsive… priced and marketed like a luxury apartment "
     "community and that's definitely not the experience.",
     None),
    (35, "a year ago", 12, False, "cut off", "Unclear", False, False, None, [], "No",
     "Typical SF apartment rental experience. Positives:…",
     "Cut off before giving a view"),
    (36, "a year ago", 12, False, "cut off", "Negative", False, False, None, ["P4"], "Yes",
     "I don't even live in the building and I go to the coffee called Progeny… The way she approached us…",
     "Café visitor, not a resident"),
    (37, "a year ago", 12, False, "none", "No text", False, False, None, [], "No", None, "Star rating only"),
    (38, "a year ago", 12, False, "full", "Positive", False, False, None, ["H1"], "Yes", "Great Service", None),
    (39, "Edited a year ago", 12, True, "cut off", "Positive", False, False, None, ["H1"], "Yes",
     "The current management at The Landing has taken the baton and run with the…",
     None),
    (40, "Edited a year ago", 12, True, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply thanks them for a 5-star review"),
    (41, "a year ago", 12, False, "cut off", "Positive", False, False, "Nicholas", ["H1", "H3"], "Yes",
     "Nicholas and the team are doing an amazing job with livening up the community here at The Landing.",
     None),
    (42, "a year ago", 12, False, "cut off", "Positive", False, False, None, ["H2"], "Yes",
     "Easily the nicest apartment I've lived in. Top of the line appliances, 10+ ft ceilings, spectacular view.",
     None),
    (43, "a year ago", 12, False, "full", "Positive", False, False, None, ["H2", "H3"], "Yes",
     "Nice ambiance, close to dogpatch, clean.",
     None),
    (44, "a year ago", 12, False, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply apologises"),
    (45, "a year ago", 12, False, "cut off", "Positive", False, False, None, ["H1"], "Yes",
     "I moved in right as the management changed and have had an incredible experience with the new management. "
     "They are extremely helpful, someone is always here even on weekends",
     None),
    (46, "a year ago", 12, False, "cut off", "Negative", True, False, None, ["P1", "P2"], "Yes",
     "New management is not better than the old one. Poor communication during the management change. Move out "
     "experience is terrible… Wall paint charge is overpriced",
     None),
    (47, "a year ago", 12, False, "cut off", "Mixed", False, False, None, ["P3"], "Yes",
     "Overall has been a nice experience. Major flaw is the utilities… we have been charged anywhere from $80-$175 "
     "for WATER ALONE on some months.",
     None),
    (48, "a year ago", 12, False, "full", "Positive", False, True, "Marissa", ["H1"], "Yes",
     "Marissa was awesome!! She explained everything in the showing and process.",
     None),
    (49, "a year ago", 12, False, "cut off", "Negative", True, False, None, ["P2"], "Yes",
     "Do yourself a favor and avoid this place at all costs! I had a terrible experience with this apartment "
     "complex. They didn't return my…",
     "Deposit theme and move-out taken from the owner's reply, which dates the move-out before the current "
     "management"),
    (50, "a year ago", 12, False, "cut off", "Negative", False, False, None, ["P3", "P5"], "Yes",
     "It's stupidly overpriced and poorly designed. The building has like 0 signs… The game room is terrible for "
     "hosting",
     None),
    (51, "a year ago", 12, False, "cut off", "Mixed", True, False, None, ["H3"], "Yes",
     "Great common area spaces and great for hosting. Gym is well equipped. Package service is great… Apartment "
     "itself was pretty average.",
     None),
    (52, "Edited a year ago", 12, True, "cut off", "Negative", False, False, None, ["P4", "P5"], "Yes",
     "Do not rent here. We moved in thinking it was going to be a great; fun amenities, nice people, friendly staff "
     "etc... It was the opposite.",
     None),
    (53, "a year ago", 12, False, "none", "No text", False, False, None, [], "Yes",
     None, "Star rating only; the owner's reply notes it had no text"),
]

WATCH = [
    "Review 26 (about Jan 2026) calls the building's practices “illegal, shady, predatory”. The owner's "
    "reply ties it to a lease buy-out clause.",
    "Review 12 praised the building a year ago (the owner's reply thanks them for it) and has since been edited to "
    "a negative review.",
    "Reviews 54 and 55 are one household's account of one unpaid deposit (the owner's replies say so), so that "
    "deposit counts twice in the deposit and former-resident figures.",
]

# The Latest Update card, for this copy only: what it shows against the copy
# before it, and what changed on the page with it. build() refuses to publish it
# under any other copy date, so the next refresh rewrites it rather than carrying
# these words forward. Like the assessment, a point may name a "metric" the page
# computes and prints in front of it -- "new", "replies_added", "tone" or
# "theme:<code>", each against the earlier copy -- so no count is typed here and
# the findings cite review numbers.
UPDATE = {
    "copied": "2026-10-19",
    "shows": [
        {"metric": "replies_added", "lead": "Owner replies have caught up",
         "finding": "They went up in one batch in the two weeks before this copy, naming the new property manager "
                    "and offering to talk (3, 6, 14, 17). One answers an earlier version of a review that has since "
                    "been rewritten as a complaint (22)."},
        {"metric": "theme:P2", "lead": "A deposit dispute is the newest complaint",
         "finding": "One household that moved out in January says a refund of nearly $6,000 was still unpaid in "
                    "October, past the 21 days its lease allows (54, 55). The owner's replies say the account is "
                    "under review."},
        {"metric": "theme:P4", "lead": "Staff conduct is now the most-raised problem",
         "finding": "The new deposit review calls management incompetent (55), review 22 now turns to staff "
                    "turnover, and the owner's reply to 14 answers concerns about the team. On Sep 30 it was level "
                    "with slow responses and fees."},
        {"metric": "tone", "lead": "Tone is a little less negative",
         "finding": "Two new negative reviews (54, 55) arrived with two positive ones (57, 58), and a rewritten "
                    "review joined the window as mixed (22), so the share fell even though the complaints grew."},
        {"metric": "theme:H1", "lead": "Praise still centres on the leasing team",
         "finding": "A new review praises a tour with the community manager (58), and Lina is still named again "
                    "and again (19, 21, 22, 27, 32), the rewritten review included."},
        {"lead": "One review is gone and two were edited",
         "finding": "The $20 Luxer late-fee complaint (23) is no longer on Google. The \u201cLina and the leasing "
                    "team are the best\u201d review (22) now opens \u201cUpdating my review\u201d and turns to "
                    "turnover, and the alarms complaint (11) was edited again."},
    ],
    "page": [
        "This card and What Changed below are new. What Changed sets the headline figures for both copies side by "
        "side and lists every change by review number.",
        "Every Review shades the reviews that are new or edited since the last copy and tags each change under its "
        "number.",
        "Review numbers now stay with their review: the new ones are 54 to 58, and every number the findings cite "
        "still points where it did.",
        "The Bottom Line's reply sentence now reads against the previous copy, so it says replies have picked back "
        "up rather than fallen off. Public replies moved to What we\u2019re doing well, and deposits now lead "
        "Where we need to improve.",
    ],
}

# The Bottom Line card's two columns. Each point names the theme whose count the
# page prints before it ("7 of 33 reviews this year"), so no count is typed here;
# "metric": "replies" prints the owner's reply rate instead. "former" adds how many
# of those reviews came from people who have moved out. Findings cite review
# numbers, and "do" is the suggested next step.
ASSESSMENT = {
    "strengths": [
        {"theme": "H1", "lead": "Leasing and tours",
         "finding": "Tours and the leasing process draw more praise than anything else here (16, 19, 27, 32, 58), "
                    "and Lina is named again and again (19, 21, 22, 27, 32).",
         "do": "Make the way Lina runs a tour the standard for the whole team, and carry that attention past "
               "move-in, which is where the reviews turn."},
        {"metric": "replies", "lead": "Public replies to reviews",
         "finding": "The owner has caught up: on Sep 30 no review from Apr–Sep 2026 had a public reply, and "
                    "most of them now do, every one posted in the two weeks before this copy. The replies name the "
                    "new property manager and offer to talk directly (3, 6, 14, 17).",
         "do": "Keep replying within a couple of days of each review rather than in catch-up batches, and answer "
               "what the review says now: review 22 has been rewritten as a complaint, and its reply still "
               "thanks it for a kind review about a package, in the words of the reply to review 21."},
        {"theme": "H2", "lead": "The apartments themselves",
         "finding": "Light, East Bay views, modern finishes and appliances are praised (13, 25, 27), a resident of "
                    "three units since 2020 says the building is still well maintained (57), and even critical "
                    "reviewers call the building nice (6, 20). The complaints are about service, not the product.",
         "do": "Lead tours and marketing with the views, light and finishes, and close the service gaps that make "
               "residents say it isn't worth the price (10, 18)."},
        {"theme": "H3", "lead": "Amenities and community spaces",
         "finding": "Residents use and like the conference room by the gym (9) and the amenities in general (13). "
                    "A year ago reviewers also praised the community and its common spaces (41, 51).",
         "do": "Promote the conference room to residents who work from home, and bring back the monthly social "
               "events one reviewer says were dropped (4)."},
    ],
    "improvements": [
        {"theme": "P2", "former": True, "lead": "Move-out and deposits",
         "finding": "A household that moved out in January says a refund of nearly $6,000 was still unpaid in "
                    "October, past the 21 days its lease allows, after refund checks it could not deposit (54, 55). "
                    "Earlier reviews describe deposits returned months late (17, 31), cleaning and repaint charges "
                    "despite a professional clean (33) and a hard move-out (20). These come from people who have "
                    "already left, and their reviews stay up.",
         "do": "Settle the refund in reviews 54 and 55 first, which the owner's replies say is under review; then "
               "audit move-out against California's 21-day deadline for returning a deposit or an itemized "
               "statement (Civil Code §1950.5), offer a walkthrough before move-out so charges are not a "
               "surprise, and pay refunds by ACH, as the owner's reply to review 31 already promised."},
        {"theme": "P4", "lead": "Staff conduct",
         "finding": "Staff described as rude, condescending, disorganized or unprofessional (3, 8, 15, 17, 20, 31), "
                    "management called incompetent (3, 4, 55), and turnover noted (22, 24). The same building "
                    "earns praise for its leasing team, so the gap is consistency.",
         "do": "Coach the on-site team on resident service, follow up on review 8 internally, and hand residents "
               "over properly when staff change."},
        {"theme": "P1", "lead": "Responsiveness",
         "finding": "Emails, calls and office visits that go unanswered, including a renewal negotiation after "
                    "five emails (6), a deposit (17) and a final lease a week before move-in (3). One reviewer "
                    "says the website, email and phone are run by AI and no one gets back (14).",
         "do": "Set a response standard, such as every email and call answered within one business day; check that "
               "questions the AI assistant can't answer reach a person; and send renewal questions straight to "
               "leasing, since an unanswered renewal is revenue at risk."},
        {"theme": "P3", "lead": "Fees and value",
         "finding": "Charges outside the lease until challenged (4), package lockers that charge residents who are "
                    "away (12), and rent seen as poor value for the service (10, 12, 18). Greedy is the word "
                    "several reviewers reach for (3, 4, 26).",
         "do": "Give every resident a one-page fee schedule at signing, audit the charges reviewers say were not "
               "in the lease, and give residents who are away longer to collect a package before the lockers "
               "charge."},
        {"theme": "P5", "lead": "Building and community upkeep",
         "finding": "A small, busy gym (10, 25), common areas less well kept and social events dropped (4), alarms "
                    "sounding all day (11), and the elevators, BBQ grills and common areas a current resident "
                    "raised, according to the owner's reply (6).",
         "do": "Bring back the monthly events, look at the gym at peak hours, give residents advance notice of "
               "alarm tests, and follow up on the elevators and BBQ grills raised in review 6."},
    ],
}

TONES = ("Positive", "Mixed", "Negative", "Unclear", "No text")
TEXTS = ("full", "cut off", "none")
REPLIES = ("Yes", "Before edit", "No")
# The coding a recode can change; an excerpt or note rewritten in place is not one.
CODED = ("tone", "themes", "former_resident", "about_leasing", "staff_praised")


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


def previous_copy():
    """The newest stored copy older than this one -- the other half of the diff -- or None."""
    older = sorted(p for p in SNAPSHOTS.glob("*.json") if p.stem < COPIED.isoformat())
    return json.loads(older[-1].read_text(encoding="utf-8")) if older else None


def changes_since(prev, reviews):
    """What moved between the stored copy and this one, by review number.

    A review whose months_ago went DOWN has been edited since: aging only ever
    adds months, and Google dates an edited review by its latest edit."""
    was = {r["n"]: r for r in prev["reviews"]}
    now = {r["n"]: r for r in reviews}
    both = sorted(set(was) & set(now))
    edited = [n for n in both if now[n]["months_ago"] < was[n]["months_ago"]
              or (now[n]["edited"] and not was[n]["edited"])]
    return {
        "since": prev["copied"],
        "new": sorted(set(now) - set(was)),
        "gone": [{k: was[n][k] for k in ("n", "shown", "tone", "themes", "excerpt")}
                 for n in sorted(set(was) - set(now))],
        "edited": edited,
        "reply_added": [n for n in both if was[n]["owner_reply"] == "No" and now[n]["owner_reply"] != "No"],
        "recoded": [n for n in both if n not in edited and any(was[n][k] != now[n][k] for k in CODED)],
        "aged_out": [n for n in both if was[n]["months_ago"] < 12 <= now[n]["months_ago"]],
        "carried": sorted(n for n in now if now[n].get("carried_from")),
    }


def build():
    codes = [t[0] for t in THEMES]
    prev = previous_copy()
    was = {r["n"]: r for r in prev["reviews"]} if prev else {}
    reviews = []
    for r in REVIEWS:
        n, shown, months, edited, text, tone, former, leasing, staff, themes, reply, excerpt, note = r
        assert tone in TONES and text in TEXTS and reply in REPLIES, (n, tone, text, reply)
        assert set(themes) <= set(codes), (n, themes)
        assert (text == "none") == (tone == "No text") == (excerpt is None), n
        row = {
            "n": n, "shown": shown, "months_ago": months, "edited": edited, "text": text, "tone": tone,
            "former_resident": former, "about_leasing": leasing, "staff_praised": staff,
            "themes": [c for c in codes if c in themes], "owner_reply": reply, "excerpt": excerpt, "note": note,
        }
        if n in CARRIED:
            # Not in this copy, so it must read exactly as it did when last seen.
            assert n in was and all(was[n][k] == row[k] for k in row), ("carried row recoded", n)
            row["carried_from"] = was[n].get("carried_from") or prev["copied"]
        reviews.append(row)

    numbers = [r["n"] for r in reviews]
    assert len(numbers) == len(set(numbers)), "a review number is used twice"
    # A new review takes the next number. Reusing a retired one would read as an
    # edit to whatever review last held it.
    assert not was or all(n > max(was) for n in set(numbers) - set(was)), "new reviews must take the next numbers"

    # The tallies made by hand for this copy (19 Oct 2026), counted from the paste
    # before this script ran, so a slip in a row cannot change the view unnoticed.
    year = [r for r in reviews if r["months_ago"] < 12]
    old = [r for r in reviews if r["months_ago"] >= 12]
    count = lambda rows, code: sum(code in r["themes"] for r in rows)
    assert (len(reviews), len(year), len(old)) == (57, 36, 21)
    assert {c: (count(year, c), count(old, c)) for c in codes} == {
        "P1": (8, 1), "P3": (7, 3), "P4": (11, 2), "P5": (7, 2), "P2": (6, 3), "P6": (1, 0),
        "H1": (8, 6), "H2": (6, 3), "H3": (2, 3)}
    assert [sum(r["tone"] == "Negative" for r in rows) for rows in (year, old)] == [15, 6]
    assert [sum(r["owner_reply"] == "Yes" for r in rows) for rows in (year, old)] == [28, 17]

    for side in ("strengths", "improvements"):
        for item in ASSESSMENT[side]:
            assert item.get("theme") in codes or item.get("metric") == "replies", item["lead"]
            assert item["lead"] and item["finding"] and item["do"], item["lead"]

    # Update notes describe one copy: published under another date they would
    # report last time's news as this time's.
    assert UPDATE["copied"] == COPIED.isoformat(), "UPDATE describes another copy; rewrite it for this one"
    metrics = {"new", "replies_added", "tone"} | {"theme:" + c for c in codes}
    for item in UPDATE["shows"]:
        assert item["lead"] and item["finding"], item
        assert item.get("metric") is None or item["metric"] in metrics, item["metric"]
    assert all(UPDATE["page"]), "an empty page note"

    periods = [
        {"key": "old", "label": "12+ months ago", "min": 12, "max": None},
        {"key": "prior", "label": span(6, 11), "min": 6, "max": 11},
        {"key": "recent", "label": span(0, 5), "min": 0, "max": 5},
    ]
    out = {
        "_comment": "Written by scripts/build_reviews_json.py, which holds the hand coding. Never edit by hand.",
        "property": "the-landing",
        "building": "The Landing",
        "address": "1395 22nd Street, San Francisco 94107",
        "source": "Google Maps review list, newest first, copied by hand",
        "copied": COPIED.isoformat(),
        "star_ratings": False,
        "periods": periods,
        "themes": [{"code": c, "kind": k, "label": lab, "definition": d, "says": s} for c, k, lab, d, s in THEMES],
        "reviews": reviews,
        "watch": WATCH,
        "assessment": ASSESSMENT,
        "update": UPDATE,
    }
    if prev:
        ch = changes_since(prev, reviews)
        # This copy's own hand count of what moved, checked like the tallies above.
        assert (ch["new"], [g["n"] for g in ch["gone"]], ch["edited"], ch["recoded"], ch["aged_out"]) == (
            [54, 55, 56, 57, 58], [23], [11, 22], [6, 14], [33]), ch
        assert len(ch["reply_added"]) == 20 and len(ch["carried"]) == 16, ch
        out["changes"] = ch
        out["previous"] = {
            "copied": prev["copied"], "periods": prev["periods"],
            "reviews": [{k: r[k] for k in ("n", "months_ago", "tone", "themes", "owner_reply", "former_resident")}
                        for r in prev["reviews"]],
        }
    return out


def snapshot(data):
    """This copy as coded, for the next copy to be compared against."""
    return {"_comment": f"The {data['copied']} copy as coded then: the other half of the next copy's diff. "
                        "Written by scripts/build_reviews_json.py; never edit by hand.",
            "copied": data["copied"], "periods": data["periods"], "reviews": data["reviews"]}


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    (SNAPSHOTS / f"{data['copied']}.json").write_text(
        json.dumps(snapshot(data), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['reviews'])} reviews, "
          f"periods {', '.join(p['label'] for p in data['periods'])}")
    ch = data.get("changes")
    if ch:
        print(f"since {ch['since']}: new {ch['new']}, gone {[g['n'] for g in ch['gone']]}, edited {ch['edited']}, "
              f"reply added {len(ch['reply_added'])}, recoded {ch['recoded']}, aged out {ch['aged_out']}, "
              f"carried {len(ch['carried'])}")
