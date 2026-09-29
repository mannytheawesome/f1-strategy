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
}


def get_circuit_guide(circuit: str) -> dict | None:
    """Static guide data for a circuit, or None if we don't have one yet.
    Deliberately a lookup, not a fallback/best-guess -- a circuit not in
    CIRCUITS means nobody has done the (manual, source-checked) research
    for it yet, not that it should render with placeholder data."""
    return CIRCUITS.get((circuit or "").lower())
