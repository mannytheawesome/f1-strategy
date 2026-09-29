"""
Per-circuit "flashpoints" guide: real corner geometry + a verified, named
history of Safety Cars / VSCs / red flags at that circuit, for the
standalone circuit-guide page (frontend/circuits.html).

This is deliberately NOT derived from OpenF1. Two separate limitations rule
that out:
  - OpenF1's race-control feed only goes back to 2023, so any circuit's
    older, well-known incidents (the ones that actually define its
    reputation) are invisible to it entirely.
  - Even within 2023+, OpenF1 reports which of ~21 marshaling "track
    sectors" triggered a flag, not the corner. An earlier version of this
    page guessed corners from the nearest sector and got two of Baku's four
    2023-2026 incidents wrong (2024's VSC placed at Turn 3 instead of the
    real Turn 2; 2026's second SC placed at Turn 3/4 instead of the real
    Turn 1) -- both confirmed wrong against public race reports.

So every incident below is individually sourced from public race reporting
(F1.com, Sky Sports, Motorsport.com, PlanetF1, RaceFans and similar), not
computed. That makes this a hand-curated, necessarily incomplete dataset --
same tradeoff this codebase already makes for engine/circuits.py's
RESURFACING_EVENTS -- extend it deliberately, per circuit, not by trying to
automate research that requires judgment to get right.

Track-outline coordinates were read directly off a high-resolution render
of the relevant FIA circuit map, each corner plotted against a pixel grid
overlaid on that render -- not sketched from memory (an earlier pass that
WAS sketched from memory produced a shape with a self-intersecting loop
that didn't resemble the real circuit at all; this method replaced it).
"""

# Each circuit's track is a closed loop of (x, y) points in a shared 1000-
# wide viewBox (height varies by circuit's own aspect ratio), one point per
# numbered corner plus start/finish, in lap order. The frontend draws
# straight segments between them -- not curve-smoothed, but topologically
# guaranteed correct since every point is a verified real corner position.
CIRCUITS = {
    "baku": {
        "name": "Baku City Circuit",
        "location": "Baku, Azerbaijan",
        "corners": 20,
        "length_km": 6.003,
        "view_box": [0, 0, 1000, 1057],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        "points": [
            ("SF", 903.3, 201.9), ("1", 940.0, 137.7), ("2", 817.8, 40.0),
            ("3", 553.6, 359.2), ("4", 597.9, 424.8), ("5", 547.5, 542.4),
            ("6", 550.6, 577.5), ("7", 567.4, 718.0), ("8", 497.1, 684.4),
            ("9", 483.4, 696.7), ("10", 468.1, 695.1), ("11", 451.3, 689.0),
            ("12", 422.3, 670.7), ("13", 320.0, 818.8), ("14", 341.4, 915.0),
            ("15", 393.3, 1017.3), ("16", 558.2, 1014.3), ("17", 559.8, 916.6),
            ("18", 590.3, 818.8), ("19", 590.3, 730.2), ("20", 646.8, 620.3),
        ],
        # Label positions for corner numbers drawn beside the track (not
        # necessarily == the track point itself, nudged clear of the line).
        "corner_labels": [
            ["1", 950, 135], ["2", 826, 30], ["3", 520, 352], ["4", 608, 440],
            ["5", 504, 538], ["6", 558, 595], ["7", 576, 732], ["8", 500, 666],
            ["9–12", 466, 712], ["13", 296, 815], ["14", 308, 932],
            ["15", 383, 1036], ["16", 562, 1034], ["17", 568, 908],
            ["18", 598, 820], ["19", 598, 726], ["20", 656, 614],
        ],
        "start_finish": {"x1": 887, "y1": 182, "x2": 920, "y2": 222,
                          "label_x": 925, "label_y": 230},
        # Turn 5 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (3 named incidents, 2023/2025/2026).
        "highlight_point": [547.5, 542.4],
        "headline": "Turn 5 has caused a real, named incident in 3 of the "
                     "last 4 years.",
        "dek": ("Nine real, named incidents since 2018, and the pattern "
                "isn't the run through the castle section — it's Turn 5: "
                "de Vries (2023), Piastri (2025) and Albon (2026) have all "
                "gone off there. The other repeat offender is the run into "
                "Turn 1, fastest part of the lap — two tyre failures on "
                "the straight in 2021 alone, a Red Bull pile-up there in "
                "2018, another multi-car mess there in 2026."),
        # type: "SC" | "VSC" | "REDFLAG"
        "incidents": [
            {"year": 2026, "corner": "1", "corner_label": "Turn 1",
             "who": "Colapinto/Gasly/Norris pile-up", "lap": 36, "type": "SC",
             "point": [940.0, 137.7],
             "source": "formula1.com"},
            {"year": 2026, "corner": "5", "corner_label": "Turn 5",
             "who": "Albon crashes", "lap": 31, "type": "SC",
             "point": [547.5, 542.4],
             "source": "gpfans.com"},
            {"year": 2025, "corner": "5", "corner_label": "Turn 5",
             "who": "Piastri crashes", "lap": 1, "type": "SC",
             "point": [547.5, 542.4],
             "source": "planetf1.com"},
            {"year": 2024, "corner": "2", "corner_label": "Turn 2",
             "who": "Pérez/Sainz collide", "lap": 50, "type": "VSC",
             "point": [817.8, 40.0],
             "source": "planetf1.com / racefans.net"},
            {"year": 2023, "corner": "5", "corner_label": "Turn 5",
             "who": "de Vries crashes", "lap": 9, "type": "SC",
             "point": [547.5, 542.4],
             "source": "formula1.com"},
            {"year": 2022, "corner": "4", "corner_label": "Turn 4",
             "who": "Sainz, hydraulic failure", "lap": 9, "type": "VSC",
             "point": [597.9, 424.8],
             "source": "planetf1.com"},
            {"year": 2021, "corner": "straight", "corner_label": "Main straight",
             "who": "Verstappen, tyre failure while leading", "lap": 46,
             "type": "REDFLAG", "point": [872.5, 252.1],
             "source": "crash.net"},
            {"year": 2021, "corner": "straight", "corner_label": "Main straight",
             "who": "Stroll, tyre failure", "lap": 30, "type": "SC",
             "point": [787.9, 390.2],
             "source": "motorsportmagazine.com"},
            {"year": 2018, "corner": "1", "corner_label": "Turn 1",
             "who": "Verstappen/Ricciardo collide", "lap": 40, "type": "SC",
             "point": [940.0, 137.7],
             "source": "skysports.com / racefans.net"},
        ],
        "incidents_note": ("This isn't every Baku incident since 2016, only "
                            "the ones public reporting let us confirm cleanly "
                            "enough to place with confidence. One candidate "
                            "(a Gasly retirement in 2019) came back with "
                            "conflicting reports on which corner and was left "
                            "off rather than guessed."),
    },
}


def get_circuit_guide(circuit: str) -> dict | None:
    """Static guide data for a circuit, or None if we don't have one yet.
    Deliberately a lookup, not a fallback/best-guess -- a circuit not in
    CIRCUITS means nobody has done the (manual, source-checked) research
    for it yet, not that it should render with placeholder data."""
    return CIRCUITS.get((circuit or "").lower())
