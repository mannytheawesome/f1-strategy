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

    "melbourne": {
        "name": "Albert Park Circuit",
        "location": "Melbourne, Australia",
        "corners": 14,
        "length_km": 5.278,
        "view_box": [0, 0, 1000, 850],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Geometry is the CURRENT layout only (raced 2022-2025 onward, post the
        # 2021 reconfiguration that cut the track from 16 to 14 corners) -- read
        # directly off the official FIA "2024 Australian Grand Prix - Circuit
        # Map" PDF (fia.com), gridded and verified, not sketched from memory.
        "points": [
            ("SF", 580.4, 619.1), ("1", 476.2, 497.6), ("2", 481.2, 445.5),
            ("3", 320.0, 249.6), ("4", 369.6, 222.3), ("5", 379.5, 128.0),
            ("6", 533.3, 40.0), ("7", 563.0, 66.0), ("8", 617.6, 68.5),
            ("9", 749.0, 517.4), ("10", 808.6, 505.0), ("11", 959.8, 775.3),
            ("12", 778.8, 800.1), ("13", 811.0, 718.3), ("14", 736.6, 762.9),
        ],
        "corner_labels": [
            ["1", 450, 500], ["2", 455, 435], ["3", 290, 250], ["4", 340, 205],
            ["5", 352, 110], ["6", 533, 15], ["7", 563, 40], ["8", 650, 60],
            ["9", 720, 540], ["10", 835, 495], ["11", 985, 790], ["12", 778, 828],
            ["13", 838, 710], ["14", 705, 790],
        ],
        "start_finish": {"x1": 563, "y1": 601, "x2": 598, "y2": 637,
                          "label_x": 605, "label_y": 648},
        # Turn 6 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (4 named incidents across 2023/2024/2025x2).
        "highlight_point": [533.3, 40.0],
        "headline": "Turn 6 has caused a real, named incident every year since "
                     "2023 — twice in 2025 alone.",
        "dek": ("Four real, named incidents at the same corner in three years: "
                "Albon (2023), Russell (2024, the first Grand Prix in F1 "
                "history to finish under a Virtual Safety Car), then Doohan "
                "and Alonso both in the same 2025 race. Melbourne added a "
                "gravel trap at Turn 6 specifically because of Russell's "
                "crash — it didn't stop the next two. The other repeat "
                "offender is Turn 2, right after the start: a Verstappen "
                "engine failure in 2022 and a Magnussen wheel-rim failure in "
                "2023 both stopped the race from exactly the same spot."),
        "incidents": [
            {"year": 2025, "corner": "6", "corner_label": "Turn 6",
             "who": "Alonso crashes in gravel", "lap": 34, "type": "SC",
             "point": [533.3, 40.0],
             "source": "motorsport.com / planetf1.com"},
            {"year": 2025, "corner": "14", "corner_label": "Turn 14",
             "who": "Sainz crashes behind the SC", "lap": 2, "type": "SC",
             "point": [736.6, 762.9],
             "source": "formula1.com / racefans.net"},
            {"year": 2025, "corner": "6", "corner_label": "Turn 6",
             "who": "Doohan crashes on lap 1", "lap": 1, "type": "SC",
             "point": [533.3, 40.0],
             "source": "formula1.com"},
            {"year": 2024, "corner": "6", "corner_label": "Turn 6",
             "who": "Russell crashes, race finishes under VSC", "lap": 57,
             "type": "VSC", "point": [533.3, 40.0],
             "source": "motorsport.com / planetf1.com / the-race.com"},
            {"year": 2023, "corner": "2", "corner_label": "Turn 2",
             "who": "Magnussen loses rear-right wheel rim on the wall", "lap": 54,
             "type": "SC", "point": [481.2, 445.5],
             "source": "formula1.com"},
            {"year": 2023, "corner": "6", "corner_label": "Turn 6",
             "who": "Albon crashes, red flag for debris", "lap": 8, "type": "REDFLAG",
             "point": [533.3, 40.0],
             "source": "speedcafe.com"},
            {"year": 2022, "corner": "2", "corner_label": "Turn 2",
             "who": "Verstappen retires, engine fire", "lap": 39, "type": "VSC",
             "point": [481.2, 445.5],
             "source": "motorsport.com / formula1.com"},
            {"year": 2022, "corner": "4", "corner_label": "Turn 4",
             "who": "Vettel spins into the wall on the exit kerb", "lap": 23,
             "type": "SC", "point": [369.6, 222.3],
             "source": "formula1.com"},
        ],
        "incidents_note": ("Restricted to the current 14-turn layout raced "
                            "since 2022 — Albert Park's pre-2022 configuration "
                            "(16 turns, two later removed) doesn't map cleanly "
                            "onto this geometry, so older, well-known incidents "
                            "(the record three red flags across the whole "
                            "2023-and-earlier history, the 2016 Alonso/Gutierrez "
                            "crash) aren't placed here rather than guessed onto "
                            "the new numbering. Two 2025 candidates (Lawson and "
                            "Bortoleto's late spins in the rain, laps 46-47) "
                            "were also left off — real, but sourcing on the "
                            "exact corner and cause was thinner than the eight "
                            "above."),
    },

    "jeddah": {
        "name": "Jeddah Corniche Circuit",
        "location": "Jeddah, Saudi Arabia",
        "corners": 27,
        "length_km": 6.175,
        "view_box": [0, 0, 1000, 742],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA 2023 Saudi Arabian GP "Event Notes -
        # Circuit Map" PDF (27 numbered corners), one grid-referenced pixel
        # reading pass, single coordinate space.
        "points": [
            ("SF", 750.1, 504.8), ("1", 676.9, 463.6), ("2", 663.0, 475.1),
            ("3", 655.0, 432.4), ("4", 572.0, 360.7), ("5", 541.0, 362.8),
            ("6", 525.2, 321.7), ("7", 494.4, 287.0), ("8", 470.6, 287.0),
            ("9", 449.6, 256.7), ("10", 460.8, 220.9), ("11", 446.1, 187.3),
            ("12", 435.7, 157.0), ("13", 320.0, 40.0), ("14", 360.1, 127.8),
            ("15", 382.8, 180.8), ("16", 399.1, 218.1), ("17", 388.2, 249.1),
            ("18", 438.7, 314.1), ("19", 489.6, 350.9), ("20", 540.4, 401.8),
            ("21", 596.9, 431.3), ("22", 655.2, 502.6), ("23", 676.0, 508.4),
            ("24", 700.2, 532.5), ("25", 726.2, 628.2), ("26", 827.0, 701.9),
            ("27", 970.0, 697.6),
        ],
        "corner_labels": [
            ["1", 690, 450], ["2", 645, 495], ["3", 662, 415], ["4", 588, 345],
            ["5", 522, 348], ["6", 540, 306], ["7", 500, 268], ["8", 452, 278],
            ["9", 430, 244], ["10", 478, 206], ["11", 428, 176], ["12", 418, 144],
            ["13", 300, 24], ["14", 378, 116], ["15", 400, 172], ["16", 416, 224],
            ["17", 368, 258], ["18", 456, 308], ["19", 506, 344], ["20", 556, 396],
            ["21", 610, 414], ["22", 638, 520], ["23", 692, 492], ["24", 716, 548],
            ["25", 742, 624], ["26", 824, 720], ["27", 984, 680],
        ],
        "start_finish": {"x1": 735, "y1": 488, "x2": 765, "y2": 522,
                          "label_x": 800, "label_y": 555},
        # Turn 22 is drawn as a highlighted ring -- the repeat flashpoint
        # (Schumacher 2021, Stroll 2024, both spinning into the Turn 23 wall).
        "highlight_point": [655.2, 502.6],
        "headline": "Turn 22 has bitten a car in 2 of Jeddah's 5 races run so "
                     "far — both times spinning straight into the Turn 23 wall.",
        "dek": ("Every single Jeddah race held since its 2021 debut has needed "
                "a Safety Car or red flag — 5 for 5 (the scheduled 2026 race "
                "was cancelled outright, not run). The clearest repeat is Turn "
                "22: Schumacher's red-flag-triggering crash in 2021 and "
                "Stroll's Safety Car shunt in 2024 are almost the same "
                "accident three years apart, both losing the car at Turn 22 "
                "and hitting the Turn 23 barrier. 2021 alone needed two "
                "separate red flags — the second from a Turn 3 pileup that "
                "eliminated four cars in one moment on the restart."),
        "incidents": [
            {"year": 2025, "corner": "4", "corner_label": "Turn 4",
             "who": "Gasly/Tsunoda collide, Gasly out on the spot", "lap": 1,
             "type": "SC", "point": [572.0, 360.7],
             "source": "autosport.com / formula1.com"},
            {"year": 2024, "corner": "22", "corner_label": "Turn 22",
             "who": "Stroll crashes, into the Turn 23 wall", "lap": 6,
             "type": "SC", "point": [655.2, 502.6],
             "source": "formula1.com / gpfans.com"},
            {"year": 2023, "corner": "13", "corner_label": "Turn 13",
             "who": "Stroll stops with an engine issue", "lap": 18,
             "type": "SC", "point": [320.0, 40.0],
             "source": "formula1.com / sportskeeda.com"},
            {"year": 2022, "corner": "27", "corner_label": "Turn 27",
             "who": "Latifi crashes", "lap": 17, "type": "SC",
             "point": [970.0, 697.6],
             "source": "lightsoutblog.com / gpblog.com"},
            {"year": 2021, "corner": "22", "corner_label": "Turn 22",
             "who": "Schumacher crashes, into the Turn 23 wall", "lap": 10,
             "type": "REDFLAG", "point": [655.2, 502.6],
             "source": "formula1.com / planetf1.com"},
            {"year": 2021, "corner": "3", "corner_label": "Turn 3",
             "who": "Perez/Leclerc contact triggers Russell/Mazepin crash",
             "lap": 15, "type": "REDFLAG", "point": [655.0, 432.4],
             "source": "racefans.net / formula1.com"},
        ],
        "incidents_note": ("This isn't every Jeddah caution since 2021 — a "
                            "couple of 2021's own Virtual Safety Cars (loose "
                            "front wing debris, then a piece of Vettel's "
                            "bodywork on track) came back with no source "
                            "specific enough to name a corner, and were left "
                            "off rather than guessed. The scheduled 2026 Saudi "
                            "Arabian Grand Prix was cancelled outright (an F1 "
                            "announcement tied to the 2026 Iran war), so "
                            "there's a genuine one-year gap in this record, "
                            "not a missing data point."),
    },

    "sakhir": {
        "name": "Bahrain International Circuit",
        "location": "Sakhir, Bahrain",
        "corners": 15,
        "length_km": 5.412,
        "view_box": [0, 0, 1000, 960],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read off the official FIA "2022 Bahrain" circuit-map PDF (the
        # standard Grand Prix layout, not the Outer/Endurance configs).
        "points": [
            ("SF", 348.5, 580.0), ("1", 438.5, 40.0), ("2", 489.5, 92.5),
            ("3", 570.5, 71.5), ("4", 962.0, 202.0), ("5", 806.0, 328.0),
            ("6", 773.0, 394.0), ("7", 716.0, 382.0), ("8", 572.0, 481.0),
            ("9", 641.0, 241.0), ("10", 575.0, 186.4), ("11", 512.0, 715.0),
            ("12", 722.0, 571.0), ("13", 857.0, 697.0), ("14", 333.5, 911.5),
            ("15", 320.0, 860.5),
        ],
        "corner_labels": [
            ["1", 439, 22], ["2", 500, 80], ["3", 580, 52], ["4", 974, 200],
            ["5", 818, 318], ["6", 785, 407], ["7", 698, 368], ["8", 538, 497],
            ["9", 653, 233], ["10", 543, 173], ["11", 478, 732],
            ["12", 734, 563], ["13", 869, 693], ["14", 298, 937],
            ["15", 268, 853],
        ],
        "start_finish": {"x1": 333, "y1": 578, "x2": 364, "y2": 582,
                          "label_x": 372, "label_y": 590},
        # Turn 1 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (3 named Safety Cars across 3 different eras).
        "highlight_point": [438.5, 40.0],
        "headline": "Turn 1 has triggered a real, named Safety Car in "
                     "three separate eras — 2014, 2022 and 2025.",
        "dek": ("Eight real, named incidents since 2007, and the clearest "
                "repeat is Turn 1 — the tight right-hander off the pit "
                "straight has brought out the Safety Car in three "
                "different eras: Maldonado's pit-exit collision with "
                "Gutiérrez (2014), Gasly's electrical fire (2022) and the "
                "Tsunoda/Sainz contact (2025). The single wildest race is "
                "still 2020: Grosjean's fireball red flag at Turn 3, "
                "Stroll flipped by Kvyat at Turn 8 on the restart, and "
                "Pérez's late engine fire at Turn 10 — three separate "
                "safety interruptions in one Grand Prix."),
        "incidents": [
            {"year": 2025, "corner": "1", "corner_label": "Turn 1",
             "who": "Tsunoda/Sainz collide", "lap": 32, "type": "SC",
             "point": [438.5, 40.0],
             "source": "formula1.com / racefans.net"},
            {"year": 2023, "corner": "13", "corner_label": "Turn 13",
             "who": "Leclerc, engine failure", "lap": 41, "type": "VSC",
             "point": [857.0, 697.0],
             "source": "formula1.com"},
            {"year": 2022, "corner": "1", "corner_label": "Turn 1",
             "who": "Gasly, electrical fire", "lap": 46, "type": "SC",
             "point": [438.5, 40.0],
             "source": "planetf1.com / gpfans.com"},
            {"year": 2020, "corner": "10", "corner_label": "Turn 10",
             "who": "Pérez, engine fire while leading", "lap": 54,
             "type": "SC", "point": [575.0, 186.4],
             "source": "formula1.com"},
            {"year": 2020, "corner": "8", "corner_label": "Turn 8",
             "who": "Stroll flipped by Kvyat", "lap": 3, "type": "SC",
             "point": [572.0, 481.0],
             "source": "formula1.com / motorsportmagazine.com"},
            {"year": 2020, "corner": "3", "corner_label": "Turn 3",
             "who": "Grosjean crashes, fireball", "lap": 1,
             "type": "REDFLAG", "point": [570.5, 71.5],
             "source": "formula1.com / espn.com"},
            {"year": 2014, "corner": "1", "corner_label": "Turn 1",
             "who": "Maldonado flips into Gutiérrez", "lap": 41,
             "type": "SC", "point": [438.5, 40.0],
             "source": "formula1.com / crash.net"},
            {"year": 2007, "corner": "4", "corner_label": "Turn 4",
             "who": "Sutil/Button/Speed collide", "lap": 1, "type": "SC",
             "point": [962.0, 202.0],
             "source": "autosport.com"},
        ],
        "incidents_note": ("This isn't every Bahrain incident since 2007, "
                            "only the ones public reporting let us confirm "
                            "cleanly enough to place at a specific corner. "
                            "Left off rather than guessed: Sainz and "
                            "Stroll's 2017 collision happened at the pit "
                            "lane exit, not a numbered corner; Hülkenberg's "
                            "and Ricciardo's separate 2019 retirements and "
                            "Mazepin's 2021 lap-1 retirement were reported "
                            "only as 'trackside' with no corner named; "
                            "Ricciardo's 2018 VSC had no corner given "
                            "either. The 2020 Sakhir Grand Prix "
                            "(Leclerc/Verstappen/Pérez pile-up, Aitken's "
                            "crash) ran on Bahrain's separate, shorter "
                            "Outer Circuit layout, not the Grand Prix "
                            "layout mapped here, so it's excluded rather "
                            "than mixed in."),
    },

    "suzuka": {
        "name": "Suzuka Circuit",
        "location": "Suzuka, Japan",
        "corners": 18,
        "length_km": 5.807,
        "view_box": [0, 0, 1000, 1406],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read off the official FIA Japanese GP circuit-map PDF. Suzuka is a
        # genuine figure-8 -- the track crosses itself once via a real
        # overpass (segment 9->10 crosses 14->15) -- that single crossing is
        # a real track feature, not a data bug; verified algebraically that
        # it's the ONLY crossing (an earlier pass had 2 extra spurious ones
        # from a misread hairpin cluster, fixed and re-checked).
        "points": [
            ("SF", 960.0, 853.5), ("1", 925.3, 1321.2), ("2", 823.1, 1365.5),
            ("3", 798.1, 1174.7), ("4", 790.4, 1107.2), ("5", 801.9, 1016.6),
            ("6", 771.1, 922.1), ("7", 785.3, 772.5), ("8", 562.9, 748.6),
            ("9", 460.7, 650.3), ("10", 599.5, 498.0), ("11", 643.9, 404.7),
            ("12", 487.7, 411.3), ("13", 360.5, 89.3), ("14", 320.0, 40.0),
            ("15", 561.0, 633.0), ("16", 818.1, 642.6), ("17", 818.1, 700.4),
            ("18", 922.2, 729.3),
        ],
        "corner_labels": [
            ["1", 940, 1300], ["2", 826, 1352], ["3", 820, 1140],
            ["4", 812, 1075], ["5", 826, 988], ["6", 794, 896],
            ["7", 808, 750], ["8", 573, 752], ["9", 432, 650],
            ["10", 617, 489], ["11", 661, 397], ["12", 458, 404],
            ["13", 378, 84], ["14", 298, 24], ["15", 535, 641],
            ["16", 822, 608], ["17", 840, 686], ["18", 941, 703],
        ],
        "start_finish": {"x1": 944, "y1": 834, "x2": 978, "y2": 873,
                          "label_x": 900, "label_y": 820},
        # Turn 1 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (3 named Safety Cars, 2010/2012/2023).
        "highlight_point": [925.3, 1321.2],
        "headline": "Turn 1 has triggered a real, named Safety Car in 3 "
                     "separate years.",
        "dek": ("Nine real, named incidents since 2005, and the clearest "
                "repeat offender is Turn 1 — the tight uphill right-hander "
                "right after the long pit straight, where first-lap chaos "
                "has brought out the Safety Car in 2010 (Massa/Liuzzi), 2012 "
                "(Alonso/Räikkönen) and 2023 (Pérez/Hamilton). The rest of "
                "the lap has its own scars: Ricciardo and Albon's 2024 "
                "opening-lap red flag came at Turn 3 in the Esses, and "
                "Bianchi's catastrophic 2014 crash into a recovery vehicle "
                "— the crash that led directly to the Virtual Safety Car "
                "being invented — happened at Turn 7, the Dunlop Curve."),
        "incidents": [
            {"year": 2023, "corner": "1", "corner_label": "Turn 1",
             "who": "Pérez/Hamilton collide (Sargeant/Bottas also tangle)",
             "lap": 1, "type": "SC", "point": [925.3, 1321.2],
             "source": "espn.com"},
            {"year": 2012, "corner": "1", "corner_label": "Turn 1",
             "who": "Alonso spins after contact with Räikkönen", "lap": 1,
             "type": "SC", "point": [925.3, 1321.2],
             "source": "crash.net"},
            {"year": 2010, "corner": "1", "corner_label": "Turn 1",
             "who": "Massa/Liuzzi collide", "lap": 1, "type": "SC",
             "point": [925.3, 1321.2],
             "source": "autosport.com"},
            {"year": 2024, "corner": "3", "corner_label": "Turn 3",
             "who": "Ricciardo/Albon collide entering the Esses", "lap": 1,
             "type": "REDFLAG", "point": [798.1, 1174.7],
             "source": "planetf1.com"},
            {"year": 2014, "corner": "7", "corner_label": "Turn 7 (Dunlop Curve)",
             "who": "Bianchi crashes into recovery vehicle (recovering Sutil's car)",
             "lap": 43, "type": "REDFLAG", "point": [785.3, 772.5],
             "source": "motorsport.com"},
            {"year": 2023, "corner": "11", "corner_label": "Turn 11 (Hairpin)",
             "who": "Pérez/Magnussen collide", "lap": 12, "type": "VSC",
             "point": [643.9, 404.7],
             "source": "racefans.net"},
            {"year": 2022, "corner": "12", "corner_label": "Turn 12",
             "who": "Sainz crashes in heavy rain", "lap": 1, "type": "REDFLAG",
             "point": [487.7, 411.3],
             "source": "formula1.com"},
            {"year": 2009, "corner": "15", "corner_label": "Turn 15 (130R)",
             "who": "Alguersuari crashes", "lap": 44, "type": "SC",
             "point": [561.0, 633.0],
             "source": "racefans.net"},
            {"year": 2005, "corner": "18", "corner_label": "Turn 18 (final corner)",
             "who": "Montoya crashes exiting the final corner", "lap": 2,
             "type": "SC", "point": [922.2, 729.3],
             "source": "planetf1.com"},
        ],
        "incidents_note": ("This isn't every Suzuka incident on record, only "
                            "the ones public reporting let us pin to a specific "
                            "numbered corner. Several were left off rather than "
                            "guessed: 2018's Leclerc/Magnussen Safety Car was "
                            "real and well documented, but every source places "
                            "the contact and resulting debris on the start/finish "
                            "straight itself, not a numbered corner, so it "
                            "doesn't fit this corner-keyed list; 1994's Herbert "
                            "spin (the first Safety Car in F1 history) and 2011's "
                            "debris call were both reported with two different, "
                            "conflicting locations depending on the source."),
    },

    "shanghai": {
        "name": "Shanghai International Circuit",
        "location": "Shanghai, China",
        "corners": 16,
        "length_km": 5.451,
        "view_box": [0, 0, 1000, 664],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read off the official FIA circuit-map PDF. An earlier pass grabbed
        # corner 12's LABEL TEXT position instead of its track apex (the
        # label sits ~150px away from the actual corner there), which
        # produced a self-intersecting 11-12-13 cluster -- re-derived by
        # isolating the track-fill pixels directly (not label text) and
        # verified with an exact segment-intersection check: 0 crossings.
        "points": [
            ("SF", 685.5, 467.9), ("1", 390.6, 561.0), ("2", 385.5, 458.7),
            ("3", 450.7, 535.1), ("4", 476.8, 468.1), ("5", 347.6, 360.4),
            ("6", 320.0, 212.4), ("7", 486.8, 367.1), ("8", 597.6, 307.2),
            ("9", 666.9, 370.6), ("10", 725.8, 317.6), ("11", 581.1, 114.1),
            ("12", 560.3, 107.8), ("13", 551.9, 40.0), ("14", 970.0, 623.6),
            ("15", 915.1, 608.6), ("16", 843.3, 453.1),
        ],
        "corner_labels": [
            ["1", 375, 577], ["2", 365, 468], ["3", 437, 552], ["4", 460, 483],
            ["5", 326, 359], ["6", 301, 201], ["7", 465, 366], ["8", 602, 287],
            ["9", 689, 370], ["10", 746, 310], ["11", 603, 108], ["12", 538, 102],
            ["13", 537, 18], ["14", 988, 636], ["15", 933, 622], ["16", 864, 460],
        ],
        "start_finish": {"x1": 681, "y1": 459, "x2": 690, "y2": 498,
                          "label_x": 706, "label_y": 516},
        # Turn 6 is drawn as a highlighted ring -- the repeat flashpoint
        # (three named incidents across three different eras: 2010/2019/2024).
        "highlight_point": [320.0, 212.4],
        "headline": "Turn 6 has triggered a Safety Car or VSC in three "
                     "different decades — 2010, 2019 and 2024.",
        "dek": ("Nine real, named incidents since 2005, and the pattern is "
                "Turn 6 — the tightening, blind-entry hairpin at the top of "
                "the esses has swallowed cars across three different eras of "
                "this race: a lap-1 pile-up in 2010 (Liuzzi spins into "
                "Kobayashi and Buemi), Norris's McLaren launched into Kvyat's "
                "Toro Rosso there in 2019, and Magnussen clipping Tsunoda out "
                "of a Safety Car restart in 2024. The other repeat offender is "
                "Turn 10 — Montoya's infamous loose-drain-cover retirement in "
                "2005, then Stroll spearing into Pérez there on the opening "
                "lap of 2017."),
        "incidents": [
            {"year": 2026, "corner": "1", "corner_label": "Turn 1",
             "who": "Stroll spins, car stranded", "lap": 10, "type": "SC",
             "point": [390.6, 561.0],
             "source": "racingnews365.com / coffeecornermotorsport.com"},
            {"year": 2024, "corner": "6", "corner_label": "Turn 6",
             "who": "Magnussen collides with Tsunoda", "lap": 27, "type": "SC",
             "point": [320.0, 212.4],
             "source": "formula1.com / motorsport.com"},
            {"year": 2024, "corner": "11", "corner_label": "Turn 11",
             "who": "Bottas retires, power unit", "lap": 22, "type": "VSC",
             "point": [581.1, 114.1],
             "source": "racefans.net"},
            {"year": 2019, "corner": "6", "corner_label": "Turn 6",
             "who": "Kvyat/Sainz/Norris collide", "lap": 1, "type": "VSC",
             "point": [320.0, 212.4],
             "source": "motorsportmagazine.com"},
            {"year": 2018, "corner": "14", "corner_label": "Turn 14",
             "who": "Gasly/Hartley (Toro Rosso teammates) collide", "lap": 30,
             "type": "SC", "point": [970.0, 623.6],
             "source": "motorsport.com / espn.com"},
            {"year": 2017, "corner": "10", "corner_label": "Turn 10",
             "who": "Stroll/Pérez collide", "lap": 1, "type": "VSC",
             "point": [725.8, 317.6],
             "source": "racefans.net"},
            {"year": 2010, "corner": "6", "corner_label": "Turn 6",
             "who": "Liuzzi spins into Kobayashi and Buemi", "lap": 1,
             "type": "SC", "point": [320.0, 212.4],
             "source": "en.wikipedia.org / thecheckeredflag.co.uk"},
            {"year": 2005, "corner": "13", "corner_label": "Turn 13",
             "who": "Karthikeyan crashes heavily", "lap": 29, "type": "SC",
             "point": [551.9, 40.0],
             "source": "crash.net / grandprix.com"},
            {"year": 2005, "corner": "10", "corner_label": "Turn 10",
             "who": "Montoya hits loose drain cover, retires", "lap": 18,
             "type": "SC", "point": [725.8, 317.6],
             "source": "grandprix.com"},
        ],
        "incidents_note": ("This isn't every Chinese GP incident since 2004, "
                            "only the ones public reporting let us confirm "
                            "cleanly enough to place with confidence. Sebastian "
                            "Buemi's spectacular double-front-wheel-loss crash "
                            "at Turn 14 remains one of Shanghai's most-replayed "
                            "moments, but it happened in first practice, not "
                            "the race, so it's left off this list. Likewise, "
                            "Nico Hulkenberg's 2026 retirement-triggered "
                            "Safety Car was in the Sprint, not the Grand Prix. "
                            "The 2025 Chinese Grand Prix ran its full race "
                            "distance without a Safety Car, VSC or red flag at "
                            "all. The two 2005 incidents' driver/corner/cause "
                            "are each corroborated by 2+ independent sources; "
                            "their exact lap numbers rest on one dedicated "
                            "source (a Safety Car history site) that a second "
                            "outlet couldn't independently confirm."),
    },

    "catalunya": {
        "name": "Circuit de Barcelona-Catalunya",
        "location": "Montmeló, Spain",
        "corners": 14,
        "length_km": 4.657,
        "view_box": [0, 0, 1000, 875],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Geometry is the CURRENT layout only (raced 2023 onward, post the
        # reconfiguration that removed the old final chicane before the pit
        # straight, turning the last corner into a fast sweeper -- 14
        # numbered corners, down from 16). Read directly off the official
        # FIA "2024 Barcelona Event - Circuit Map" PDF: corner-number
        # glyphs isolated by exact pixel color (pure blue, distinct from
        # the yellow/red FIA Marshal Light numbers sharing the same
        # digits), each snapped to the nearest track-centerline pixel
        # rather than used at the label's own position -- the fix applied
        # after Shanghai/Suzuka's spurious self-intersections. Verified 0
        # crossings via check_crossings.py.
        "points": [
            ("SF", 821.3, 391.6), ("1", 541.6, 816.1), ("2", 484.1, 788.9),
            ("3", 320.0, 831.1), ("4", 449.7, 522.8), ("5", 407.5, 717.3),
            ("6", 554.0, 699.9), ("7", 617.6, 593.3), ("8", 565.0, 551.7),
            ("9", 518.5, 373.1), ("10", 862.9, 173.2), ("11", 772.5, 160.5),
            ("12", 693.9, 179.0), ("13", 795.9, 40.0), ("14", 960.0, 158.8),
        ],
        "corner_labels": [
            ["1", 536, 841], ["2", 474, 813], ["3", 308, 851], ["4", 425, 531],
            ["5", 391, 737], ["6", 547, 725], ["7", 616, 619], ["8", 550, 573],
            ["9", 499, 356], ["10", 879, 153], ["11", 784, 137], ["12", 700, 154],
            ["13", 806, 16], ["14", 979, 141],
        ],
        "start_finish": {"x1": 808.7, "y1": 374.1, "x2": 833.9, "y2": 409.1,
                          "label_x": 853, "label_y": 412},
        # Turn 10 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (2 named Safety Cars, 2021 and 2025, both mechanical
        # failures into the same gravel trap).
        "highlight_point": [862.9, 173.2],
        "headline": "Turn 10 has ended a Grand Prix early twice in the last "
                     "five years — both times the same failure, a car "
                     "stranded in the gravel trap on the run out of the back "
                     "straight.",
        "dek": ("Six real, named incidents since 2016, and the closest thing "
                "to a repeat is Turn 10: Tsunoda's engine failure triggered "
                "the Safety Car there in 2021, and Antonelli's retirement did "
                "the same in 2025 — four years and one full circuit "
                "reconfiguration apart, same corner, same result. Barcelona-"
                "Catalunya is otherwise one of the calendar's quietest circuits "
                "for cautions — which makes 2026's Barcelona-Catalunya Grand "
                "Prix (the Spanish GP itself moved to Madrid's new Madring "
                "circuit that year) stand out: it alone needed two separate "
                "Virtual Safety Cars, one for Alonso's home-race retirement at "
                "Turn 9 and another for Leclerc's late hydraulic failure at "
                "Turn 2."),
        "incidents": [
            {"year": 2026, "corner": "9", "corner_label": "Turn 9",
             "who": "Alonso retires, battery/technical failure", "lap": 41,
             "type": "VSC", "point": [518.5, 373.1],
             "source": "formula1.com / honda.racing"},
            {"year": 2026, "corner": "2", "corner_label": "Turn 2",
             "who": "Leclerc retires, hydraulic/power-steering failure",
             "lap": 63, "type": "VSC", "point": [484.1, 788.9],
             "source": "formula1.com / racingnews365.com / crash.net"},
            {"year": 2025, "corner": "10", "corner_label": "Turn 10",
             "who": "Antonelli retires, mechanical failure", "lap": 55,
             "type": "SC", "point": [862.9, 173.2],
             "source": "en.wikipedia.org / formula1.com"},
            {"year": 2021, "corner": "10", "corner_label": "Turn 10",
             "who": "Tsunoda retires, engine failure", "lap": 8, "type": "SC",
             "point": [862.9, 173.2],
             "source": "lightsoutblog.com"},
            {"year": 2017, "corner": "1", "corner_label": "Turn 1",
             "who": "Vandoorne/Massa collide", "lap": 34, "type": "VSC",
             "point": [541.6, 816.1],
             "source": "lightsoutblog.com"},
            {"year": 2016, "corner": "3", "corner_label": "Turn 3",
             "who": "Rosberg/Hamilton collide (Mercedes teammates, lap 1)",
             "lap": 1, "type": "SC", "point": [320.0, 831.1],
             "source": "lightsoutblog.com / skysports.com"},
        ],
        "incidents_note": ("The 2023 and 2024 Spanish Grands Prix both ran "
                            "their full distance with no Safety Car, VSC or "
                            "red flag at all -- a genuine gap, not a missing "
                            "data point. Left off rather than guessed: "
                            "Verstappen's deliberate lap-64 collision with "
                            "Russell in 2025 was real and heavily reported, "
                            "but it happened under green-flag racing after an "
                            "earlier Safety Car had already been withdrawn and "
                            "didn't itself trigger a new caution, so it doesn't "
                            "fit this SC/VSC/red-flag-keyed list. A 2008 "
                            "Sutil/Vettel Safety Car is real but sources split "
                            "on whether it was Turn 3 or Turn 4, so it's "
                            "excluded rather than guessed. Norris/Stroll's "
                            "2019 Safety Car and a multi-car 2009 pile-up both "
                            "happened at the old final chicane before the pit "
                            "straight — removed in the 2023 "
                            "reconfiguration — so neither maps onto the "
                            "current layout and both are excluded, the same "
                            "convention Melbourne's entry uses for its own "
                            "pre-reconfiguration incidents."),
    },

    "spielberg": {
        "name": "Red Bull Ring",
        "location": "Spielberg, Austria",
        "corners": 10,
        "length_km": 4.318,
        "view_box": [0, 0, 1000, 491],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2020 Austrian Grand Prix -
        # Circuit Map" PDF -- the modern 10-corner layout raced since 2016,
        # gridded and verified corner-by-corner against actual track-edge
        # pixels (not label text -- this map's yellow boxes are a separate
        # "FIA Marshal Light No." sequence that looks similar to the blue
        # corner numbers at a glance). Verified 0 crossings.
        "points": [
            ("SF", 823.7, 381.5), ("1", 567.6, 451.0), ("2", 434.6, 148.5),
            ("3", 320.0, 40.0), ("4", 734.6, 83.9), ("5", 654.1, 144.9),
            ("6", 496.8, 153.4), ("7", 562.7, 281.5), ("8", 668.8, 224.1),
            ("9", 939.5, 218.0), ("10", 970.0, 322.9),
        ],
        "corner_labels": [
            ["1", 556, 476], ["2", 412, 141], ["3", 301, 29], ["4", 746, 65],
            ["5", 655, 125], ["6", 477, 144], ["7", 544, 294], ["8", 679, 204],
            ["9", 962, 206], ["10", 991, 330],
        ],
        "start_finish": {"x1": 808, "y1": 366, "x2": 840, "y2": 398,
                          "label_x": 846, "label_y": 408},
        # Turn 3 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (6 named incidents across 5 of the last 7 races here).
        "highlight_point": [320.0, 40.0],
        "headline": "Turn 3 has triggered a Safety Car or VSC in 5 of the 7 "
                     "Austrian Grands Prix run since the circuit's 2020 "
                     "return — twice in the same race in 2020 alone.",
        "dek": ("Nine real, named incidents since 2000, and the pattern is "
                "overwhelmingly Turn 3 — the tight right-hander that opens "
                "the circuit's climb has brought out a Safety Car or VSC in "
                "five of the seven races run here since 2020: Leclerc "
                "collecting Vettel there on lap 1 of the 2020 Styrian GP, "
                "Magnussen (lap 26) and Russell (lap 51) both stopped there "
                "in the very same 2020 Austrian GP, Ocon sandwiched entering "
                "it on lap 1 in 2021, Verstappen and Norris colliding there "
                "fighting for the lead in 2024, and Antonelli taking "
                "Verstappen out there on the opening lap of 2025. The "
                "circuit's short lap means most of these are first-lap "
                "incidents rather than mechanical failures — the "
                "exceptions are Vettel's 2016 tyre explosion on the start "
                "straight and Sainz's 2022 engine fire at Turn 4."),
        "incidents": [
            {"year": 2025, "corner": "3", "corner_label": "Turn 3",
             "who": "Antonelli crashes into Verstappen", "lap": 1, "type": "SC",
             "point": [320.0, 40.0],
             "source": "autosport.com / planetf1.com"},
            {"year": 2024, "corner": "3", "corner_label": "Turn 3",
             "who": "Verstappen and Norris collide fighting for the lead",
             "lap": 64, "type": "VSC", "point": [320.0, 40.0],
             "source": "autosport.com / gpfans.com"},
            {"year": 2022, "corner": "4", "corner_label": "Turn 4",
             "who": "Sainz retires, engine fire", "lap": 57, "type": "VSC",
             "point": [734.6, 83.9],
             "source": "motorsport.com"},
            {"year": 2021, "corner": "3-4", "corner_label": "Turns 3/4",
             "who": "Ocon retires, sandwiched between Giovinazzi and Schumacher",
             "lap": 1, "type": "SC", "point": [527.3, 62.0],
             "source": "formula1.com"},
            {"year": 2020, "corner": "3", "corner_label": "Turn 3",
             "who": "Leclerc spins into teammate Vettel (Styrian GP)", "lap": 1,
             "type": "SC", "point": [320.0, 40.0],
             "source": "formula1.com"},
            {"year": 2020, "corner": "3", "corner_label": "Turn 3",
             "who": "Magnussen, brake failure", "lap": 26, "type": "SC",
             "point": [320.0, 40.0],
             "source": "lightsoutblog.com"},
            {"year": 2020, "corner": "3", "corner_label": "Turn 3",
             "who": "Russell, fuel pressure loss (Grosjean also retires same lap)",
             "lap": 51, "type": "SC", "point": [320.0, 40.0],
             "source": "motorsport.com"},
            {"year": 2016, "corner": "straight", "corner_label": "Start/finish straight",
             "who": "Vettel, tyre explosion while leading", "lap": 27,
             "type": "SC", "point": [860.0, 368.0],
             "source": "skysports.com / autoblog.com"},
            {"year": 2000, "corner": "1", "corner_label": "Turn 1",
             "who": "Zonta punts Schumacher out at the first corner", "lap": 1,
             "type": "SC", "point": [567.6, 451.0],
             "source": "racefans.net / f1.fandom.com"},
        ],
        "incidents_note": ("This isn't every Austrian GP incident since 2000, "
                            "only the ones public reporting let us confirm "
                            "cleanly enough to place at a specific corner. Left "
                            "off rather than guessed: 2002's Heidfeld/Sato "
                            "crash is real and well documented, but the most "
                            "detailed account places it spanning Turn 2 and "
                            "Turn 3, conflicting with a flatter 'Turn 3' from a "
                            "second source; 2023's Tsunoda/Ocon lap-1 Safety "
                            "Car had contact reported at the exit of Turn 1 but "
                            "the gravel excursion that actually brought out the "
                            "Safety Car at Turn 4 — two different corners "
                            "depending on which part of the incident you'd "
                            "plot; 2023's Hulkenberg (lap 14) and 2018's Bottas "
                            "(lap 14) Virtual Safety Cars were both reported "
                            "only as mechanical retirements with no corner "
                            "named."),
    },

    "montreal": {
        "name": "Circuit Gilles Villeneuve",
        "location": "Montreal, Canada",
        "corners": 14,
        "length_km": 4.361,
        "view_box": [0, 0, 1000, 2150],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2024 Canadian Grand Prix -
        # Event Notes - Circuit Map" PDF, gridded and verified against
        # actual track-fill pixels (not label text), current 14-turn
        # layout only (the 1996-2001 configuration had 13 turns with
        # different numbering through the middle of the lap -- see
        # incidents_note). Verified 0 crossings.
        "points": [
            ("SF", 902.4, 1791.5), ("1", 896.5, 2062.6), ("2", 960.0, 2101.7),
            ("3", 603.4, 1960.0), ("4", 637.6, 1908.7), ("5", 432.4, 1710.8),
            ("6", 403.1, 1469.0), ("7", 351.8, 1465.6), ("8", 320.0, 736.2),
            ("9", 364.0, 728.9), ("10", 449.5, 40.0), ("11", 503.2, 181.7),
            ("12", 574.0, 357.6), ("13", 811.0, 1311.7), ("14", 796.3, 1325.9),
        ],
        "corner_labels": [
            ["1", 855, 2062], ["2", 930, 2130], ["3", 575, 1985], ["4", 655, 1885],
            ["5", 460, 1715], ["6", 430, 1460], ["7", 310, 1470], ["8", 290, 745],
            ["9", 395, 715], ["10", 449, 15], ["11", 535, 175], ["12", 605, 355],
            ["13", 845, 1300], ["14", 760, 1345],
        ],
        "start_finish": {"x1": 880, "y1": 1780, "x2": 925, "y2": 1803,
                          "label_x": 930, "label_y": 1770},
        # Turn 14 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (4 named incidents: 1999 x2, 2005, 2007), the wall that
        # gave the corner its "Wall of Champions" nickname in the first place.
        "highlight_point": [796.3, 1325.9],
        "headline": "The Wall of Champions has caused a real, named Safety "
                     "Car in 4 separate years — twice in the very 1999 "
                     "race that gave it its name.",
        "dek": ("Twelve real, named Safety Cars since 1999, and the clearest "
                "repeat is the final-chicane wall itself: Ricardo Zonta and "
                "Jacques Villeneuve both hit it in the same 1999 race that "
                "coined \"Wall of Champions,\" and Jenson Button (2005) and "
                "Vitantonio Liuzzi (2007) each added their own. The next-"
                "clearest pattern is Turn 2, the tight right-hander onto the "
                "pit straight — Nick Heidfeld was launched into the barrier "
                "there by Kamui Kobayashi in 2011's rain-hit, six-Safety-Car "
                "\"longest race in F1 history,\" and Yuki Tsunoda speared "
                "into the same wall exiting the pits in 2022. Turn 4 has its "
                "own quieter repeat too: Adrian Sutil's gearbox fire there "
                "in 2007, then Jules Bianchi launched into the wall by "
                "teammate Max Chilton on the opening lap of 2014."),
        "incidents": [
            {"year": 2023, "corner": "9", "corner_label": "Turn 9",
             "who": "Russell crashes on exit, running wide", "lap": 12,
             "type": "SC", "point": [364.0, 728.9],
             "source": "formula1.com / racingnews365.com"},
            {"year": 2022, "corner": "2", "corner_label": "Turn 2",
             "who": "Tsunoda crashes exiting the pits", "lap": 49,
             "type": "SC", "point": [960.0, 2101.7],
             "source": "racefans.net / formula1.com"},
            {"year": 2014, "corner": "1", "corner_label": "Turn 1",
             "who": "Massa/Perez collide on the final lap", "lap": 70,
             "type": "SC", "point": [896.5, 2062.6],
             "source": "skysports.com / sportskeeda.com"},
            {"year": 2014, "corner": "4", "corner_label": "Turn 4",
             "who": "Bianchi launched into the wall by teammate Chilton",
             "lap": 1, "type": "SC", "point": [637.6, 1908.7],
             "source": "racefans.net"},
            {"year": 2011, "corner": "2", "corner_label": "Turn 2",
             "who": "Heidfeld launched into the wall by Kobayashi", "lap": 56,
             "type": "SC", "point": [960.0, 2101.7],
             "source": "racefans.net"},
            {"year": 2008, "corner": "3", "corner_label": "Turn 3",
             "who": "Sutil, gearbox failure and fire", "lap": 17,
             "type": "SC", "point": [603.4, 1960.0],
             "source": "racefans.net / gpfans.com"},
            {"year": 2007, "corner": "10", "corner_label": "Turn 10 (hairpin)",
             "who": "Kubica launched into the wall after contact with Fisichella",
             "lap": 27, "type": "SC", "point": [449.5, 40.0],
             "source": "motorsport.com / racingnews365.com"},
            {"year": 2007, "corner": "14", "corner_label": "Turn 14 (Wall of Champions)",
             "who": "Liuzzi crashes", "lap": 56, "type": "SC",
             "point": [796.3, 1325.9],
             "source": "lightsoutblog.com"},
            {"year": 2007, "corner": "4", "corner_label": "Turn 4",
             "who": "Sutil crashes into the wall", "lap": 23, "type": "SC",
             "point": [637.6, 1908.7],
             "source": "grandprix.com / lightsoutblog.com"},
            {"year": 2005, "corner": "14", "corner_label": "Turn 14 (Wall of Champions)",
             "who": "Button crashes", "lap": 47, "type": "SC",
             "point": [796.3, 1325.9],
             "source": "formula1.com / lightsoutblog.com"},
            {"year": 1999, "corner": "14", "corner_label": "Turn 14 (Wall of Champions)",
             "who": "Villeneuve crashes, understeers into the wall", "lap": 37,
             "type": "SC", "point": [796.3, 1325.9],
             "source": "lightsoutblog.com / motorsportmagazine.com"},
            {"year": 1999, "corner": "14", "corner_label": "Turn 14 (Wall of Champions)",
             "who": "Zonta crashes, the incident that named the wall", "lap": 4,
             "type": "SC", "point": [796.3, 1325.9],
             "source": "lightsoutblog.com / motorsportmagazine.com"},
        ],
        "incidents_note": ("This isn't every Montreal incident since 1999, "
                            "only the ones public reporting let us confirm "
                            "cleanly enough to place at a specific corner. "
                            "Montreal's own 2001 Wall of Champions incident "
                            "(Barrichello) came back with a corner given as "
                            "Turn 4 in one detailed race report but credited "
                            "to the Wall of Champions itself with no lap in "
                            "another, and was left off rather than guessed. "
                            "Kevin Magnussen's 2019 Wall of Champions crash "
                            "and Max Verstappen/Alex Albon's 2024 versions "
                            "were real but happened in Qualifying and Free "
                            "Practice respectively, not the race. Sergio "
                            "Pérez's 2022 retirement (lap 8, VSC) had no "
                            "corner given in any source. The dramatic 2026 "
                            "race (Antonelli's win, a late Norris/Piastri "
                            "collision, Russell's retirement, two more VSCs) "
                            "is excluded entirely — neither F1.com's own "
                            "report nor follow-up coverage names a specific "
                            "corner for any of its incidents. Corner numbers "
                            "before Montreal's 2002 layout change (13 turns, "
                            "not 14, with different numbering through the "
                            "middle of the lap) aren't used here except for "
                            "the Wall of Champions itself, a fixed physical "
                            "feature whose position on track hasn't moved "
                            "regardless of how the corners around it were "
                            "renumbered."),
    },

    "miami": {
        "name": "Miami International Autodrome",
        "location": "Miami Gardens, Florida",
        "corners": 19,
        "length_km": 5.412,
        "view_box": [0, 0, 1000, 340],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2026 Miami Grand Prix -
        # Circuit Map, Pit Lane Drawing, Emergency Exits Map and Red Zone"
        # PDF, gridded and verified. The map draws the front (SF) straight
        # and the back (16->17) straight running close/parallel near the
        # paddock -- re-traced at high resolution to find the real fork
        # point after SF and kept the SF->1 diagonal clear of the 16->17
        # line's y-coordinates so the two straights don't cross in this
        # straight-segment representation. Verified 0 crossings.
        "points": [
            ("SF", 567.3, 58.9), ("1", 717.6, 167.9), ("2", 703.0, 194.6),
            ("3", 700.4, 233.2), ("4", 486.6, 189.4), ("5", 433.3, 212.6),
            ("6", 382.7, 175.7), ("7", 325.2, 199.7), ("8", 320.0, 239.2),
            ("9", 562.2, 266.7), ("10", 691.0, 295.9), ("11", 914.2, 189.4),
            ("12", 897.0, 148.2), ("13", 959.7, 132.7), ("14", 961.4, 103.5),
            ("15", 970.9, 93.2), ("16", 970.0, 56.3), ("17", 399.0, 40.0),
            ("18", 433.3, 70.9), ("19", 486.6, 57.2),
        ],
        "corner_labels": [
            ["1", 735, 165], ["2", 735, 196], ["3", 735, 233], ["4", 480, 172],
            ["5", 425, 228], ["6", 378, 158], ["7", 302, 202], ["8", 296, 250],
            ["9", 558, 282], ["10", 695, 312], ["11", 930, 192], ["12", 872, 148],
            ["13", 978, 135], ["14", 938, 100], ["15", 985, 88], ["16", 985, 50],
            ["17", 370, 24], ["18", 428, 86], ["19", 486, 40],
        ],
        "start_finish": {"x1": 550, "y1": 48, "x2": 584, "y2": 68,
                          "label_x": 590, "label_y": 38},
        # Turn 14 is drawn as a highlighted ring on the page -- the only
        # corner with a verified incident in two different years (2024, 2026).
        "highlight_point": [961.4, 103.5],
        "headline": "Turn 14 has caused a real, named Safety Car or VSC in "
                     "two of Miami's five runnings so far — 2024 and 2026.",
        "dek": ("Eight real, named incidents since Miami's 2022 debut, and "
                "the clearest repeat is Turn 14, the marina-area chicane: "
                "Verstappen clattered a loose bollard there under VSC in "
                "2024, then Isack Hadjar crashed into the wall there under "
                "Safety Car in 2026. 2026 was the wildest race by far — "
                "Hadjar's Turn 14 shunt was followed moments later by Liam "
                "Lawson's gearbox failing under braking for Turn 17, pitching "
                "Pierre Gasly's Alpine into a barrel roll — two separate "
                "crashes, one Safety Car period. Turn 1 has bitten early "
                "too: Jack Doohan and Lawson collided there on the opening "
                "lap of 2025."),
        "incidents": [
            {"year": 2026, "corner": "14", "corner_label": "Turn 14",
             "who": "Hadjar crashes into the chicane wall", "lap": 5,
             "type": "SC", "point": [961.4, 103.5],
             "source": "formula1.com / gpfans.com"},
            {"year": 2026, "corner": "17", "corner_label": "Turn 17 (hairpin)",
             "who": "Gasly flipped after Lawson's gearbox fails under braking",
             "lap": 6, "type": "SC", "point": [399.0, 40.0],
             "source": "formula1.com / motorsport.com"},
            {"year": 2025, "corner": "16", "corner_label": "Turn 16",
             "who": "Bortoleto stops, power unit failure", "lap": 33,
             "type": "VSC", "point": [970.0, 56.3],
             "source": "lightsoutblog.com / en.wikipedia.org"},
            {"year": 2025, "corner": "4", "corner_label": "Turn 4",
             "who": "Bearman retires, engine failure", "lap": 28,
             "type": "VSC", "point": [486.6, 189.4],
             "source": "lightsoutblog.com / en.wikipedia.org"},
            {"year": 2025, "corner": "12", "corner_label": "Turn 12",
             "who": "Alonso spins into the barrier after Lawson contact",
             "lap": 14, "type": "SC", "point": [897.0, 148.2],
             "source": "en.wikipedia.org"},
            {"year": 2025, "corner": "1", "corner_label": "Turn 1",
             "who": "Doohan and Lawson collide, Doohan retires", "lap": 1,
             "type": "VSC", "point": [717.6, 167.9],
             "source": "en.wikipedia.org"},
            {"year": 2024, "corner": "3", "corner_label": "Turn 3",
             "who": "Magnussen and Sargeant collide, Sargeant into the wall",
             "lap": 29, "type": "SC", "point": [700.4, 233.2],
             "source": "espn.com / formula1.com"},
            {"year": 2024, "corner": "14", "corner_label": "Turn 14",
             "who": "Verstappen strikes a loose bollard in the chicane",
             "lap": 21, "type": "VSC", "point": [961.4, 103.5],
             "source": "racefans.net / gpfans.com"},
            {"year": 2022, "corner": "8", "corner_label": "Turn 8",
             "who": "Norris and Gasly collide", "lap": 41, "type": "SC",
             "point": [320.0, 239.2],
             "source": "formula1.com / crash.net"},
        ],
        "incidents_note": ("This isn't every Miami incident since 2022, only "
                            "the ones public reporting let us confirm cleanly "
                            "enough to place at a specific corner. 2023's race "
                            "ran completely clean — no Safety Car, VSC, or "
                            "red flag at all, confirmed independently by two "
                            "sources, not a missing data point. Left off "
                            "rather than guessed: 2025's late Hamilton/Sainz "
                            "contact at Turn 17 and 2026's opening-lap "
                            "Verstappen/Leclerc (Turn 1) and Hamilton/"
                            "Colapinto (Turn 11) incidents all triggered no "
                            "Safety Car or VSC, so they don't belong on this "
                            "list even though they're real, named moments. "
                            "The exact lap of 2024's Verstappen bollard VSC "
                            "varies across sources (19-23 all appear); 21 is "
                            "the most consistently cited and is used here."),
    },
}


def get_circuit_guide(circuit: str) -> dict | None:
    """Static guide data for a circuit, or None if we don't have one yet.
    Deliberately a lookup, not a fallback/best-guess -- a circuit not in
    CIRCUITS means nobody has done the (manual, source-checked) research
    for it yet, not that it should render with placeholder data."""
    return CIRCUITS.get((circuit or "").lower())
