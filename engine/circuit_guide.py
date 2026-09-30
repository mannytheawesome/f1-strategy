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

    "monte carlo": {
        "name": "Circuit de Monaco",
        "location": "Monte Carlo, Monaco",
        "corners": 19,
        "length_km": 3.337,
        "view_box": [0, 0, 1000, 930],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2025 Monaco Event - Circuit
        # Map" PDF -- corner-number label positions extracted from the
        # PDF's own vector text layer (exact, not eyeballed), then each
        # apex cross-verified against the rendered track curve on a fine
        # grid to resolve dense clusters (the 6/7/8 hairpin complex, the
        # 10/11 chicane kink, the 15/16 swimming-pool "Z" kink). Numbering
        # cross-checked against Formula1.com's own named-corner list
        # (Sainte Devote=1 ... Antony Noghes=19) and matches exactly.
        # Verified 0 crossings.
        "points": [
            ("SF", 320.0, 617.4), ("1", 362.8, 429.3), ("2", 683.3, 339.8),
            ("3", 794.3, 291.7), ("4", 759.8, 206.9), ("5", 867.9, 40.0),
            ("6", 932.1, 123.8), ("7", 917.5, 63.9), ("8", 970.0, 40.7),
            ("9", 894.2, 304.2), ("10", 656.0, 408.5), ("11", 636.4, 425.6),
            ("12", 411.6, 440.3), ("13", 370.1, 575.9), ("14", 401.9, 602.8),
            ("15", 423.4, 712.7), ("16", 410.4, 724.9), ("17", 422.6, 786.0),
            ("18", 486.2, 866.7), ("19", 401.9, 887.4),
        ],
        "corner_labels": [
            ["1", 369, 405], ["2", 655, 320], ["3", 812, 275], ["4", 715, 195],
            ["5", 850, 18], ["6", 955, 148], ["7", 878, 58], ["8", 990, 22],
            ["9", 918, 300], ["10", 660, 386], ["11", 600, 440], ["12", 385, 440],
            ["13", 335, 572], ["14", 432, 608], ["15", 452, 708], ["16", 378, 732],
            ["17", 452, 788], ["18", 518, 866], ["19", 365, 902],
        ],
        "start_finish": {"x1": 305, "y1": 610, "x2": 335, "y2": 625,
                          "label_x": 250, "label_y": 617},
        # Turn 13 (swimming pool entry) is drawn as a highlighted ring --
        # the repeat flashpoint (4 named incidents across 4 decades).
        "highlight_point": [370.1, 575.9],
        "headline": "The swimming pool section has claimed a car in four "
                     "different decades — 2003, 2008, 2011 and 2022.",
        "dek": ("Fourteen real, named incidents since 2003, and the clearest "
                "repeat is the swimming pool chicane: Frentzen (2003), "
                "Rosberg (2008), a three-car pile-up for Sutil/Alguersuari/"
                "Petrov (2011) and Mick Schumacher's car-splitting shunt "
                "(2022) have all ended there. La Rascasse has its own "
                "pattern too — Trulli mounting Chandhok's car in 2010, "
                "then Sauber team-mates Nasr and Ericsson colliding in 2016. "
                "And 2026 alone needed two separate stoppages at the very "
                "last corner, Anthony Noghes: Stroll's Safety Car crash, "
                "then Leclerc crashing into the barrier at the restart, "
                "forcing a red flag for a crumbling track surface."),
        "incidents": [
            {"year": 2026, "corner": "19", "corner_label": "Turn 19 (Antony Noghes)",
             "who": "Leclerc crashes on the SC restart, brake failure", "lap": 66,
             "type": "REDFLAG", "point": [401.9, 887.4],
             "source": "formula1.com / crash.net / gpfans.com"},
            {"year": 2026, "corner": "19", "corner_label": "Turn 19 (Antony Noghes)",
             "who": "Stroll crashes, engine-braking issue", "lap": 60, "type": "SC",
             "point": [401.9, 887.4],
             "source": "formula1.com / motorsport.com / skysports.com"},
            {"year": 2025, "corner": "8", "corner_label": "Turn 8 (Portier)",
             "who": "Bortoleto crashes after Antonelli battle", "lap": 1,
             "type": "VSC", "point": [970.0, 40.7],
             "source": "racefans.net / gpfans.com / crash.net"},
            {"year": 2024, "corner": "3", "corner_label": "Turn 3 (Massenet)",
             "who": "Pérez/Magnussen collide, Hülkenberg collected", "lap": 1,
             "type": "REDFLAG", "point": [794.3, 291.7],
             "source": "autosport.com / motorsport.com / racefans.net"},
            {"year": 2022, "corner": "15", "corner_label": "Turn 15 (Swimming Pool)",
             "who": "Schumacher crashes, car splits in half", "lap": 26,
             "type": "REDFLAG", "point": [423.4, 712.7],
             "source": "planetf1.com / espn.com / autosport.com"},
            {"year": 2018, "corner": "10", "corner_label": "Turn 10 (Nouvelle Chicane)",
             "who": "Leclerc's brakes fail, hits Hartley", "lap": 73, "type": "VSC",
             "point": [656.0, 408.5],
             "source": "racefans.net / espn.com"},
            {"year": 2016, "corner": "18", "corner_label": "Turn 18 (La Rascasse)",
             "who": "Nasr/Ericsson (Sauber team-mates) collide", "lap": 49,
             "type": "VSC", "point": [486.2, 866.7],
             "source": "espn.com / motorsport.com"},
            {"year": 2016, "corner": "3", "corner_label": "Turn 3 (Massenet)",
             "who": "Verstappen crashes", "lap": 35, "type": "VSC",
             "point": [794.3, 291.7],
             "source": "lightsoutblog.com / espn.com"},
            {"year": 2015, "corner": "1", "corner_label": "Turn 1 (Sainte Devote)",
             "who": "Verstappen hits Grosjean — first-ever F1 VSC", "lap": 64,
             "type": "VSC", "point": [362.8, 429.3],
             "source": "racefans.net / lightsoutblog.com"},
            {"year": 2013, "corner": "1", "corner_label": "Turn 1 (Sainte Devote)",
             "who": "Massa crashes, suspension failure", "lap": 30, "type": "SC",
             "point": [362.8, 429.3],
             "source": "cnn.com / autocarindia.com"},
            {"year": 2011, "corner": "13", "corner_label": "Turn 13 (Swimming Pool)",
             "who": "Sutil/Alguersuari/Petrov crash", "lap": 69, "type": "REDFLAG",
             "point": [370.1, 575.9],
             "source": "racefans.net / grandprix.com"},
            {"year": 2010, "corner": "18", "corner_label": "Turn 18 (La Rascasse)",
             "who": "Trulli mounts Chandhok's car", "lap": 75, "type": "SC",
             "point": [486.2, 866.7],
             "source": "autosport.com / crash.net"},
            {"year": 2008, "corner": "13", "corner_label": "Turn 13 (Swimming Pool)",
             "who": "Rosberg crashes hard entering the pool", "lap": 60,
             "type": "SC", "point": [370.1, 575.9],
             "source": "racefans.net / rte.ie / motorsportmagazine.com"},
            {"year": 2003, "corner": "14", "corner_label": "Turn 14 (Swimming Pool)",
             "who": "Frentzen crashes — Monaco's first-ever Safety Car", "lap": 2,
             "type": "SC", "point": [401.9, 602.8],
             "source": "grandprix.com / lightsoutblog.com"},
        ],
        "incidents_note": ("This isn't every Monaco incident since 2003, only "
                            "the ones public reporting let us confirm cleanly "
                            "enough to place at a specific corner. Left off "
                            "rather than guessed: the 2004 Schumacher/Montoya "
                            "tunnel collision happened UNDER an already-running "
                            "Safety Car (deployed for an earlier incident) "
                            "rather than triggering one itself; 2017's "
                            "Button/Wehrlein clash was reported only as "
                            "'before the tunnel,' not clearly Portier or the "
                            "tunnel itself; Leclerc's 2021 swimming-pool crash "
                            "was real and well documented but happened in "
                            "qualifying, not the race. Ayrton Senna's famous "
                            "1988 retirement at Portier isn't included for a "
                            "different reason — it predates the Safety Car's "
                            "1993 introduction to F1 entirely, so there was no "
                            "SC/VSC/red flag to record."),
    },

    "zandvoort": {
        "name": "Circuit Zandvoort",
        "location": "Zandvoort, Netherlands",
        "corners": 14,
        "length_km": 4.259,
        "view_box": [0, 0, 1000, 620],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2026 Dutch Grand Prix -
        # Competition Notes - Circuit Map" PDF, gridded and verified
        # against actual track-fill pixels (not the separate yellow "FIA
        # light panel" numbering, which shares some digits with the blue
        # corner numbers but is a different sequence). Turns 3 and 13/14
        # are genuinely banked in real life (Hugenholtzbocht, Arie
        # Luyendijkbocht) -- approximated as tight loops in this 2D plan
        # view. Verified 0 crossings.
        "points": [
            ("SF", 402.1, 258.0), ("1", 511.3, 40.0), ("2", 488.3, 235.9),
            ("3", 421.4, 305.1), ("4", 571.2, 315.7), ("5", 695.7, 292.6),
            ("6", 806.4, 277.4), ("7", 970.0, 306.2), ("8", 888.4, 487.2),
            ("9", 778.7, 449.4), ("10", 877.8, 364.1), ("11", 509.0, 397.3),
            ("12", 465.2, 381.1), ("13", 472.1, 577.1), ("14", 320.0, 544.8),
        ],
        "corner_labels": [
            ["1", 511, 20], ["2", 465, 240], ["3", 395, 308], ["4", 571, 335],
            ["5", 695, 270], ["6", 806, 255], ["7", 985, 306], ["8", 888, 507],
            ["9", 745, 449], ["10", 877, 344], ["11", 509, 377], ["12", 430, 381],
            ["13", 495, 577], ["14", 295, 545],
        ],
        "start_finish": {"x1": 384.2, "y1": 249.0, "x2": 420.0, "y2": 267.0,
                          "label_x": 435, "label_y": 277},
        # Turn 3 (the banked Hugenholtzbocht) is drawn as a highlighted ring
        # -- the repeat flashpoint (2 separate Safety Cars in 2025 alone).
        "highlight_point": [421.4, 305.1],
        "headline": "Turn 3 — the banked Hugenholtzbocht — triggered two "
                     "separate Safety Cars in the same 2025 race alone.",
        "dek": ("Eight real, named incidents since Zandvoort's 2021 return, "
                "and the clearest repeat is Turn 3: Hamilton crashed there to "
                "bring out the Safety Car on lap 22 of 2025's race, and that "
                "same afternoon Antonelli tagged Leclerc into the wall at the "
                "identical corner on lap 53. The other repeat is Turn 1, off "
                "the pit straight: Bottas's engine failure stopped there in "
                "2022, and Zhou's rain crash there in 2023 escalated into the "
                "circuit's only red flag inside a Grand Prix. 2021 and 2024 "
                "both ran their full distance with no Safety Car, VSC or red "
                "flag at all."),
        "incidents": [
            {"year": 2026, "corner": "14", "corner_label": "Turn 14 (Arie Luyendijkbocht)",
             "who": "Verstappen crashes on the opening lap, wet patch on the banking",
             "lap": 1, "type": "REDFLAG", "point": [320.0, 544.8],
             "source": "formula1.com / motorsport.com / en.wikipedia.org"},
            {"year": 2026, "corner": "5", "corner_label": "Turn 5",
             "who": "Sainz/Albon (Williams teammates) collide, debris", "lap": 70,
             "type": "VSC", "point": [695.7, 292.6],
             "source": "en.wikipedia.org"},
            {"year": 2025, "corner": "8", "corner_label": "Turn 8 (Mastersbocht)",
             "who": "Norris retires, car emitting smoke", "lap": 65, "type": "SC",
             "point": [888.4, 487.2],
             "source": "en.wikipedia.org"},
            {"year": 2025, "corner": "3", "corner_label": "Turn 3 (Hugenholtzbocht)",
             "who": "Leclerc crashes after contact from Antonelli", "lap": 53,
             "type": "SC", "point": [421.4, 305.1],
             "source": "racingnews365.com / motorsport.com"},
            {"year": 2025, "corner": "3", "corner_label": "Turn 3 (Hugenholtzbocht)",
             "who": "Hamilton crashes heavily", "lap": 22, "type": "SC",
             "point": [421.4, 305.1],
             "source": "en.wikipedia.org"},
            {"year": 2023, "corner": "1", "corner_label": "Turn 1 (Tarzanbocht)",
             "who": "Zhou aquaplanes into the barrier in heavy rain", "lap": 64,
             "type": "REDFLAG", "point": [511.3, 40.0],
             "source": "motorsport.com / racefans.net"},
            {"year": 2023, "corner": "9", "corner_label": "Turn 9",
             "who": "Sargeant crashes, loses hydraulic/steering assist", "lap": 17,
             "type": "SC", "point": [778.7, 449.4],
             "source": "racingnews365.com / gpfans.com"},
            {"year": 2022, "corner": "1", "corner_label": "Turn 1 (Tarzanbocht)",
             "who": "Bottas retires, engine failure approaching the corner",
             "lap": 55, "type": "SC", "point": [511.3, 40.0],
             "source": "en.wikipedia.org / lightsoutblog.com"},
        ],
        "incidents_note": ("This is every Dutch GP Safety Car/VSC/red flag "
                            "since Zandvoort's 2021 return that public "
                            "reporting let us confirm to a specific corner -- "
                            "2021 and 2024 both ran clean, full-distance races "
                            "with no caution at all, a genuine gap rather than "
                            "a missing data point. Left off rather than "
                            "guessed: Tsunoda's 2022 VSC-triggering retirement "
                            "(lap 47) -- sources describe an earlier stop at "
                            "the exit of Turn 4 but don't name where his "
                            "final, VSC-triggering stop happened; Ocon's 2026 "
                            "VSC-triggering retirement (lap 55) -- no source "
                            "names a corner; and a lap-31 2025 VSC for track "
                            "debris, where one account ties it to a Sainz/"
                            "Lawson clash but another separately places that "
                            "contact at Turn 1 on lap 7 with no caution "
                            "attached — conflicting enough to leave out "
                            "rather than guess."),
    },

    "hungaroring": {
        "name": "Hungaroring",
        "location": "Mogyoród, Hungary",
        "corners": 14,
        "length_km": 4.381,
        "view_box": [0, 0, 1000, 850],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2026 Hungarian Grand Prix -
        # Competition Notes - Circuit Map, Pit Lane Drawing, Emergency
        # Exits Map and Red Zone" PDF, gridded and verified against real
        # track-edge pixels (not label text -- corner numbers on this map
        # are blue; a separate, similar-looking yellow "FIA Light Panel"
        # sequence and orange marshal-post "M#" labels share the same
        # digits and were deliberately not used). 1A and 12A are the map's
        # own sub-labelled kinks within the Turn 1 and Turn 12/13
        # complexes, included as extra polyline points but not counted in
        # the corners total (14, matching the map's own numbering).
        # Verified 0 crossings.
        "points": [
            ("SF", 587.6, 700.8), ("1", 320.0, 435.5), ("1A", 434.7, 457.0),
            ("2", 597.2, 555.0), ("3", 582.9, 428.3), ("4", 688.0, 183.4),
            ("5", 716.7, 40.0), ("6", 833.8, 159.5), ("7", 826.6, 182.2),
            ("8", 857.7, 269.4), ("9", 948.5, 301.7), ("10", 922.2, 428.3),
            ("11", 970.0, 512.0), ("12", 812.3, 705.5), ("12A", 754.9, 660.1),
            ("13", 683.2, 614.7), ("14", 738.2, 792.8),
        ],
        "corner_labels": [
            ["1", 300, 438], ["1A", 405, 480], ["2", 578, 578], ["3", 556, 422],
            ["4", 665, 148], ["5", 700, 14], ["6", 850, 132], ["7", 790, 206],
            ["8", 876, 246], ["9", 972, 286], ["10", 948, 426], ["11", 994, 522],
            ["12", 820, 734], ["12A", 776, 666], ["13", 655, 606], ["14", 740, 822],
        ],
        "start_finish": {"x1": 578, "y1": 712, "x2": 598, "y2": 690,
                          "label_x": 610, "label_y": 668},
        # Turn 2 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (2 named incidents in back-to-back years, 2017/2018,
        # both involving Verstappen).
        "highlight_point": [597.2, 555.0],
        "headline": "Turn 2 has caused a real, named Safety Car or VSC in "
                     "back-to-back years — 2017 and 2018.",
        "dek": ("Five real, named incidents since 2014, and the tightest "
                "repeat is Turn 2: Daniel Ricciardo was eliminated there "
                "after contact with team-mate Max Verstappen in 2017, then "
                "Verstappen's own engine let go accelerating out of the "
                "same corner a year later. Turn 1 has its own pattern "
                "across a longer span — Nico Hülkenberg's front wing "
                "failure pitched him into the Turn 1 barrier in 2015, and "
                "Valtteri Bottas triggered a five-car pile-up and red flag "
                "there in 2021."),
        "incidents": [
            {"year": 2021, "corner": "1", "corner_label": "Turn 1",
             "who": "Bottas triggers a multi-car pile-up (Norris, "
                    "Verstappen, Pérez, Stroll, Leclerc all collected)",
             "lap": 1, "type": "REDFLAG", "point": [320.0, 435.5],
             "source": "racefans.net / en.wikipedia.org"},
            {"year": 2018, "corner": "2", "corner_label": "Turn 2",
             "who": "Verstappen retires, MGU-K failure accelerating out of "
                    "Turn 2", "lap": 6, "type": "VSC", "point": [597.2, 555.0],
             "source": "motorsportmagazine.com"},
            {"year": 2017, "corner": "2", "corner_label": "Turn 2",
             "who": "Ricciardo eliminated after contact with team-mate "
                    "Verstappen", "lap": 2, "type": "SC",
             "point": [597.2, 555.0],
             "source": "en.wikipedia.org / motorsport.com"},
            {"year": 2015, "corner": "1", "corner_label": "Turn 1",
             "who": "Hülkenberg's front wing fails, crashes into the "
                    "tyre barrier", "lap": 42, "type": "SC",
             "point": [320.0, 435.5],
             "source": "autosport.com"},
            {"year": 2014, "corner": "14", "corner_label": "Turn 14 (final corner)",
             "who": "Pérez crashes into the pit wall exiting the final corner",
             "lap": 22, "type": "SC", "point": [738.2, 792.8],
             "source": "racefans.net / bleacherreport.com"},
        ],
        "incidents_note": ("This isn't every Hungarian GP incident since "
                            "2006, only the ones public reporting let us "
                            "confirm cleanly enough to place at a specific "
                            "corner. Several real, well-documented cautions "
                            "were left off rather than guessed: Räikkönen's "
                            "2006 collision with Liuzzi (Safety Car, no "
                            "corner given by any source), 2010's Liuzzi "
                            "front-wing-debris Safety Car, 2018's separate "
                            "lap-51 Vandoorne VSC, and 2022's two VSCs "
                            "(lap-1 contact debris, Bottas's late power-unit "
                            "retirement) all came back with no corner "
                            "specific enough to plot. 2026's Piastri VSC "
                            "(gearbox failure) is a genuine, recent example "
                            "excluded for a real reason, not an oversight: "
                            "one account places it 'between turns one and "
                            "two' while another says 'exit of Turn 3' — a "
                            "real conflict on the exact corner. 2023, 2024, "
                            "2025, 2020, 2019, 2016 and 2013 each ran their "
                            "full race distance with no Safety Car, VSC or "
                            "red flag at all, not missing data points. "
                            "Tsunoda's much-covered 2024 Turn 5 shunt "
                            "happened in qualifying, not the race, so it "
                            "doesn't belong on this list either."),
    },

    "monza": {
        "name": "Autodromo Nazionale Monza",
        "location": "Monza, Italy",
        "corners": 11,
        "length_km": 5.793,
        "view_box": [0, 0, 1000, 1260],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2026 Italian Grand Prix -
        # Competition Notes - Circuit Map" PDF, gridded and verified
        # corner-by-corner against actual track-edge pixels, not label
        # text or the map's separate "FIA LIGHT PANEL" numbering (a
        # similarly-numbered but distinct sequence on the same map).
        # Monza is a fast, chicane-based lap, not a crossover layout --
        # verified 0 crossings.
        "points": [
            ("SF", 320.0, 948.9), ("1", 370.3, 431.1), ("2", 392.6, 421.8),
            ("3", 437.3, 129.4), ("4", 768.9, 69.8), ("5", 793.1, 54.9),
            ("6", 958.8, 40.0), ("7", 970.0, 187.1), ("8", 489.5, 537.3),
            ("9", 474.6, 598.7), ("10", 515.6, 628.5), ("11", 362.8, 1209.6),
        ],
        "corner_labels": [
            ["1", 345, 431], ["2", 415, 415], ["3", 408, 132], ["4", 758, 46],
            ["5", 805, 30], ["6", 968, 18], ["7", 990, 190], ["8", 452, 528],
            ["9", 438, 605], ["10", 548, 636], ["11", 362, 1236],
        ],
        "start_finish": {"x1": 305, "y1": 933, "x2": 335, "y2": 963,
                          "label_x": 345, "label_y": 948},
        # Turn 1 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (3 named incidents, 2011/2018/2019).
        "highlight_point": [370.3, 431.1],
        "headline": "Turn 1 has triggered a real, named Safety Car or VSC "
                     "in three separate years — 2011, 2018 and 2019.",
        "dek": ("Ten real, named incidents since 2000, and the clearest "
                "repeat is Turn 1, the Variante del Rettifilo — the "
                "heaviest braking zone on the lap, arriving straight off the "
                "fastest part of the track, has swallowed cars converging on "
                "it at the start in 2011 (Liuzzi collects Rosberg and Petrov "
                "after contact with Kovalainen), 2018 (Hartley pincered by "
                "Vandoorne and Ericsson) and 2019 (Kvyat's engine fails "
                "right there, late in the race). The Parabolica has an "
                "eerier repeat: Charles Leclerc has caused both of Monza's "
                "only two red flags this century — 2020 and 2026, both "
                "losing the rear exiting the final corner. The Variante "
                "della Roggia bookends two very different eras too: the "
                "marshal-fatality Safety Car of 2000 and Giovinazzi's spin "
                "there in 2021."),
        "incidents": [
            {"year": 2026, "corner": "11", "corner_label": "Turn 11 (Parabolica)",
             "who": "Leclerc crashes exiting the corner after contact with Hamilton",
             "lap": 2, "type": "REDFLAG", "point": [362.8, 1209.6],
             "source": "formula1.com / the-race.com / racefans.net"},
            {"year": 2022, "corner": "6-7", "corner_label": "Turns 6/7 (between the Lesmos)",
             "who": "Ricciardo stops trackside, mechanical failure; race finishes under SC",
             "lap": 48, "type": "SC", "point": [964.4, 113.55],
             "source": "racefans.net / autosport.com"},
            {"year": 2021, "corner": "2", "corner_label": "Turn 2 (Rettifilo chicane)",
             "who": "Verstappen lands on Hamilton after collision", "lap": 26,
             "type": "SC", "point": [392.6, 421.8],
             "source": "motorsportmagazine.com / racefans.net / espn.com"},
            {"year": 2021, "corner": "4-5", "corner_label": "Turns 4/5 (Variante della Roggia)",
             "who": "Giovinazzi runs across the chicane after a failed pass, clips Sainz",
             "lap": 1, "type": "VSC", "point": [781.0, 62.35],
             "source": "motorsport.com"},
            {"year": 2020, "corner": "11", "corner_label": "Turn 11 (Parabolica)",
             "who": "Leclerc crashes, Monza's first red flag since 1995", "lap": 23,
             "type": "REDFLAG", "point": [362.8, 1209.6],
             "source": "en.wikipedia.org / racefans.net"},
            {"year": 2019, "corner": "1", "corner_label": "Turn 1",
             "who": "Kvyat stops, engine failure", "lap": 31, "type": "VSC",
             "point": [370.3, 431.1],
             "source": "lightsoutblog.com"},
            {"year": 2018, "corner": "1", "corner_label": "Turn 1",
             "who": "Hartley pincered by Vandoorne and Ericsson", "lap": 1,
             "type": "SC", "point": [370.3, 431.1],
             "source": "motorsportmagazine.com / talkmotorsport.co.nz"},
            {"year": 2011, "corner": "1", "corner_label": "Turn 1",
             "who": "Liuzzi collects Rosberg and Petrov after contact with Kovalainen",
             "lap": 1, "type": "SC", "point": [370.3, 431.1],
             "source": "racefans.net / formula1.com / crash.net"},
            {"year": 2007, "corner": "3", "corner_label": "Turn 3 (Curva Grande)",
             "who": "Coulthard crashes, car failure", "lap": 2, "type": "SC",
             "point": [437.3, 129.4],
             "source": "racefans.net"},
            {"year": 2000, "corner": "4-5", "corner_label": "Turns 4/5 (Variante della Roggia)",
             "who": "Frentzen/Trulli/Coulthard/Barrichello incident — marshal "
                    "Paolo Gislimberti fatally struck by a flying wheel",
             "lap": 1, "type": "SC", "point": [781.0, 62.35],
             "source": "grandprix.com / en.wikipedia.org / racefans.net"},
        ],
        "incidents_note": ("This isn't every Monza incident since 2000, only "
                            "the ones public reporting let us confirm cleanly "
                            "enough to place at a specific corner. Left off "
                            "rather than guessed: 2019's Sainz VSC (stopped at "
                            "pit exit, not a numbered corner) and 2020's "
                            "Magnussen SC (stopped near pit entry); 2022's "
                            "Vettel VSC (lap 12) was never reported against a "
                            "specific corner. The 2026 Hamilton/Leclerc contact "
                            "at Turn 2 was real and heavily covered but "
                            "triggered no SC/VSC/red flag (stewards took no "
                            "action), so it doesn't belong on this list. 2025's "
                            "Italian Grand Prix ran its full distance with no "
                            "Safety Car, VSC or red flag at all, confirmed "
                            "across multiple race reports, not a missing data "
                            "point. Corners before 1972 (when the two "
                            "chicanes were added to slow the circuit down) "
                            "aren't used here at all — 1978's Ronnie Peterson "
                            "fatality and 1961's disaster both predate the "
                            "Safety Car's own introduction to F1 in 1973."),
    },

    "spa-francorchamps": {
        "name": "Circuit de Spa-Francorchamps",
        "location": "Stavelot, Belgium",
        "corners": 19,
        "length_km": 7.004,
        "view_box": [0, 0, 1000, 1100],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2026 Belgian Grand Prix -
        # Circuit Map, Pit Lane Drawing, Emergency Exits Map and Red Zone"
        # PDF (fia.com), gridded and read corner-by-corner off the actual
        # track-edge pixels. The map's blue "CORNER NUMBER" labels (1-19)
        # were carefully kept separate from its yellow "FIA LIGHT PANEL"
        # boxes (01-21) -- a visually similar but unrelated numbering on
        # the same map. Corner-to-name mapping (La Source, Eau Rouge/
        # Raidillon, Les Combes, Pouhon, Fagnes, Blanchimont, Bus Stop,
        # etc.) cross-checked against formula1.com's own named-corner list
        # and matches the pixel-read topology exactly. Verified 0
        # crossings.
        "points": [
            ("SF", 501.7, 235.6), ("1", 439.0, 40.0), ("2", 687.0, 259.3),
            ("3", 761.0, 276.6), ("4", 756.1, 341.8), ("5", 960.0, 866.1),
            ("6", 937.7, 898.2), ("7", 950.2, 977.3), ("8", 784.2, 1049.4),
            ("9", 829.1, 997.0), ("10", 789.1, 703.7), ("11", 685.4, 763.0),
            ("12", 578.3, 952.6), ("13", 499.3, 923.2), ("14", 390.6, 1029.1),
            ("15", 320.0, 962.5), ("16", 548.6, 705.1), ("17", 590.6, 586.6),
            ("18", 546.2, 312.1), ("19", 563.5, 288.9),
        ],
        "corner_labels": [
            ["1", 439, 20], ["2", 705, 250], ["3", 779, 268], ["4", 774, 338],
            ["5", 978, 860], ["6", 952, 912], ["7", 968, 980], ["8", 784, 1068],
            ["9", 848, 995], ["10", 808, 698], ["11", 682, 784], ["12", 576, 972],
            ["13", 497, 903], ["14", 372, 1044], ["15", 296, 962], ["16", 528, 703],
            ["17", 570, 582], ["18", 524, 308], ["19", 582, 284],
        ],
        "start_finish": {"x1": 486, "y1": 220, "x2": 518, "y2": 252,
                          "label_x": 524, "label_y": 214},
        # Turn 1 (La Source) is drawn as a highlighted ring on the page --
        # the repeat flashpoint (5 named incidents across 4 different
        # years, including twice in the very same 1998 race).
        "highlight_point": [439.0, 40.0],
        "headline": "Turn 1 (La Source) has caused a Safety Car or Red "
                     "Flag in 4 separate years — including twice in the "
                     "very same 1998 race.",
        "dek": ("Twenty real, named incidents across Spa's long history, and "
                "the clearest repeat is Turn 1 — the tight hairpin right "
                "after the start/finish straight has triggered chaos in "
                "1998 (a 13-car red-flag pileup on the first start, then a "
                "Hakkinen/Herbert Safety Car on the second), 2012 (Grosjean "
                "launched over Alonso), 2018 (Hülkenberg into Alonso, who "
                "flew over Leclerc's halo) and 2019 (Räikkönen/"
                "Verstappen). Les Combes has its own repeat pattern across "
                "an even wider spread of eras — 2009, 2011, 2016 and 2026 "
                "all saw a Safety Car or VSC start there. And Spa's length "
                "and weather have twice cancelled a race outright: 2021's "
                "near-total washout (the entire race classified from barely "
                "more than one lap behind the Safety Car) and 2025's "
                "rain-delayed start, both red-flagged before real racing "
                "could begin."),
        "incidents": [
            {"year": 2026, "corner": "5", "corner_label": "Turn 5 (Les Combes)",
             "who": "Hamilton understeers into Russell, who spins into the gravel",
             "lap": 1, "type": "SC", "point": [960.0, 866.1],
             "source": "formula1.com / grandprix247.com"},
            {"year": 2025, "corner": "straight", "corner_label": "Start/finish straight",
             "who": "Red-flagged on the formation lap for torrential rain; "
                    "race delayed ~80 minutes, restarted behind the Safety Car",
             "lap": 0, "type": "REDFLAG", "point": [501.7, 235.6],
             "source": "crash.net / planetf1.com / racefans.net"},
            {"year": 2022, "corner": "6", "corner_label": "Turn 6 (Les Combes)",
             "who": "Latifi runs wide exiting Les Combes and collects Bottas; "
                    "Hamilton also stranded", "lap": 2, "type": "SC",
             "point": [937.7, 898.2],
             "source": "en.wikipedia.org"},
            {"year": 2021, "corner": "straight", "corner_label": "Start/finish straight",
             "who": "Race red-flagged for rain after 2 laps behind the Safety "
                    "Car and never restarted — classified from lap 1, half points",
             "lap": 3, "type": "REDFLAG", "point": [501.7, 235.6],
             "source": "en.wikipedia.org / formula1.com"},
            {"year": 2020, "corner": "14", "corner_label": "Turn 14 (Campus)",
             "who": "Giovinazzi crashes exiting the corner, wheel hits Russell's car",
             "lap": 10, "type": "SC", "point": [390.6, 1029.1],
             "source": "en.wikipedia.org"},
            {"year": 2019, "corner": "1", "corner_label": "Turn 1 (La Source)",
             "who": "Räikkönen turns into Verstappen, who later hits the "
                    "Turn 4 barrier", "lap": 1, "type": "SC",
             "point": [439.0, 40.0],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 2018, "corner": "1", "corner_label": "Turn 1 (La Source)",
             "who": "Hülkenberg hits Alonso, who flies over Leclerc's halo",
             "lap": 1, "type": "SC", "point": [439.0, 40.0],
             "source": "racefans.net / espn.com"},
            {"year": 2017, "corner": "2", "corner_label": "Turn 2 (Eau Rouge)",
             "who": "Pérez squeezes Ocon (Force India teammates), debris SC",
             "lap": 30, "type": "SC", "point": [687.0, 259.3],
             "source": "racefans.net / motorsport.com"},
            {"year": 2016, "corner": "3", "corner_label": "Turn 3 (Raidillon)",
             "who": "Magnussen crashes at 12.5g, damages the barrier",
             "lap": 9, "type": "REDFLAG", "point": [761.0, 276.6],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 2016, "corner": "5", "corner_label": "Turn 5 (Les Combes)",
             "who": "Sainz, tyre failure", "lap": 1, "type": "VSC",
             "point": [960.0, 866.1],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 2015, "corner": "18", "corner_label": "Turn 18 (Bus Stop)",
             "who": "Ricciardo retires, system failure — F1's first-ever VSC",
             "lap": 20, "type": "VSC", "point": [546.2, 312.1],
             "source": "lightsoutblog.com / fia.com"},
            {"year": 2012, "corner": "1", "corner_label": "Turn 1 (La Source)",
             "who": "Grosjean launches over Alonso; Hamilton, Pérez, "
                    "Kobayashi also collected", "lap": 1, "type": "SC",
             "point": [439.0, 40.0],
             "source": "racefans.net / en.wikipedia.org"},
            {"year": 2011, "corner": "5", "corner_label": "Turn 5 (Les Combes)",
             "who": "Hamilton and Kobayashi collide, Hamilton retires",
             "lap": 13, "type": "SC", "point": [960.0, 866.1],
             "source": "en.wikipedia.org"},
            {"year": 2009, "corner": "5", "corner_label": "Turn 5 (Les Combes)",
             "who": "Grosjean into Button; Hamilton and Alguersuari also crash",
             "lap": 1, "type": "SC", "point": [960.0, 866.1],
             "source": "en.wikipedia.org"},
            {"year": 2005, "corner": "3", "corner_label": "Turn 3 (Raidillon)",
             "who": "Fisichella spins and hits the barrier heavily",
             "lap": 11, "type": "SC", "point": [761.0, 276.6],
             "source": "autosport.com / en.wikipedia.org"},
            {"year": 2004, "corner": "straight", "corner_label": "Kemmel Straight",
             "who": "Coulthard hits the back of Klien, debris in bodywork",
             "lap": 39, "type": "SC", "point": [858.1, 604.0],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 2004, "corner": "straight", "corner_label": "Kemmel Straight",
             "who": "Button, rear tyre failure at ~205mph, hits Baumgartner",
             "lap": 31, "type": "SC", "point": [858.1, 604.0],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 2004, "corner": "2", "corner_label": "Turn 2 (Eau Rouge)",
             "who": "Sato/Webber/Pantano/Bruni collide, fire on Bruni's car",
             "lap": 1, "type": "SC", "point": [687.0, 259.3],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 1998, "corner": "1", "corner_label": "Turn 1 (La Source)",
             "who": "Häkkinen spins, Herbert crashes into him (second start)",
             "lap": 1, "type": "SC", "point": [439.0, 40.0],
             "source": "grandprix.com / lightsoutblog.com"},
            {"year": 1998, "corner": "1", "corner_label": "Turn 1 (La Source)",
             "who": "13-car pileup on the run out of La Source in the rain "
                    "(first start)", "lap": 1, "type": "REDFLAG",
             "point": [439.0, 40.0],
             "source": "formula1.com / en.wikipedia.org"},
        ],
        "incidents_note": ("This isn't every Belgian GP incident on record, "
                            "only the ones public reporting let us confirm "
                            "cleanly enough to place at a specific corner. "
                            "Left off rather than guessed: a widely-repeated "
                            "claim of a lap-28 Fisichella/Nakano Bus Stop "
                            "collision in the 1998 race came back "
                            "contradicted by other sources (Fisichella "
                            "actually retired lap 26 with no Bus Stop "
                            "mention, and Nakano finished the race) and was "
                            "dropped. Several other listed cautions (1995, "
                            "1996, 1997, 2000, a second 2010 incident) had no "
                            "corner named in any source and are excluded. "
                            "The 2023 Belgian Grand Prix ran its full race "
                            "distance clean — no Safety Car, VSC or red "
                            "flag at all (that weekend's SC drama was "
                            "entirely in the Sprint, excluded here, matching "
                            "the convention used elsewhere in this file). "
                            "2017's earlier lap-1 Pérez/Ocon contact (a "
                            "separate incident from their SC-triggering "
                            "lap-30 clash) isn't confirmed to have itself "
                            "caused a caution, so only the lap-30 one is "
                            "listed."),
    },

    "silverstone": {
        "name": "Silverstone Circuit",
        "location": "Silverstone, United Kingdom",
        "corners": 18,
        "length_km": 5.891,
        "view_box": [0, 0, 1000, 1180],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2025 British Grand Prix -
        # Circuit Map" PDF (fia.com), gridded and verified corner-by-corner
        # against actual track-fill pixels (not label text -- this map's
        # yellow boxes are a separate "FIA Marshal Light No." sequence,
        # not corner numbers). The Vale/Club double-apex (16-18) needed
        # particular care: the map draws a second, parallel grey band
        # there that is pit lane (runs alongside the main straight,
        # terminates near the Club hairpin at pit entry) rather than a
        # second piece of track -- resolved via pixel scanning before
        # placing those points. Verified 0 crossings.
        "points": [
            ("SF", 368.3, 798.3), ("1", 540.3, 588.9), ("2", 639.0, 596.9),
            ("3", 787.9, 505.0), ("4", 845.8, 583.9), ("5", 860.5, 457.2),
            ("6", 485.8, 202.4), ("7", 443.8, 272.5), ("8", 498.8, 91.2),
            ("9", 837.0, 40.0), ("10", 928.5, 390.0), ("11", 953.7, 426.9),
            ("12", 934.8, 523.5), ("13", 960.0, 632.6), ("14", 905.9, 681.3),
            ("15", 578.1, 1136.2), ("16", 443.8, 934.7), ("17", 372.5, 957.8),
            ("18", 320.0, 876.0),
        ],
        "corner_labels": [
            ["1", 536, 565], ["2", 635, 575], ["3", 770, 485], ["4", 862, 600],
            ["5", 880, 455], ["6", 480, 180], ["7", 415, 275], ["8", 495, 68],
            ["9", 845, 18], ["10", 948, 385], ["11", 972, 425], ["12", 953, 520],
            ["13", 978, 630], ["14", 884, 690], ["15", 578, 1158],
            ["16", 418, 930], ["17", 350, 970], ["18", 298, 876],
        ],
        "start_finish": {"x1": 353, "y1": 783, "x2": 384, "y2": 814,
                          "label_x": 390, "label_y": 825},
        # Turn 1 (Abbey) is drawn as a highlighted ring on the page -- the
        # repeat flashpoint (3 named incidents across 3 different eras:
        # 2016/2018/2022, and 3 different caution types).
        "highlight_point": [540.3, 588.9],
        "headline": "Turn 1 (Abbey) has triggered a real, named caution in "
                     "three different eras — 2016, 2018 and 2022.",
        "dek": ("Nine real, named incidents since 2014, and the clearest "
                "repeat is Abbey — the fast right-hander right after the "
                "pit straight has caught out Wehrlein aquaplaning there in "
                "2016, Ericsson crashing in 2018, and Zhou's frightening "
                "barrel roll there in 2022. The next-clearest pattern is "
                "Copse, the daunting high-speed right-hander a third of the "
                "way round the lap — Grosjean and Sainz collided there in "
                "2018, and Verstappen and Hamilton's title-fight crash there "
                "in 2021 needed a full red flag to repair the barrier. "
                "2025's rain-hit race alone needed separate stoppages at "
                "The Loop and Farm inside the first six laps."),
        "incidents": [
            {"year": 2025, "corner": "2", "corner_label": "Turn 2 (Farm)",
             "who": "Bortoleto spins, damages rear wing", "lap": 6, "type": "VSC",
             "point": [639.0, 596.9],
             "source": "racefans.net"},
            {"year": 2025, "corner": "4", "corner_label": "Turn 4 (The Loop)",
             "who": "Ocon collides with Lawson", "lap": 1, "type": "VSC",
             "point": [845.8, 583.9],
             "source": "lightsoutblog.com / medium.com"},
            {"year": 2023, "corner": "straight", "corner_label": "Wellington Straight",
             "who": "Magnussen, power unit fire", "lap": 33, "type": "SC",
             "point": [673.2, 329.8],
             "source": "formula1.com"},
            {"year": 2022, "corner": "1", "corner_label": "Turn 1 (Abbey)",
             "who": "Zhou barrel-rolls after contact with Russell/Gasly",
             "lap": 1, "type": "REDFLAG", "point": [540.3, 588.9],
             "source": "motorsport.com / skysports.com"},
            {"year": 2021, "corner": "9", "corner_label": "Turn 9 (Copse)",
             "who": "Verstappen/Hamilton collide", "lap": 1, "type": "REDFLAG",
             "point": [837.0, 40.0],
             "source": "racefans.net / autosport.com"},
            {"year": 2018, "corner": "9", "corner_label": "Turn 9 (Copse)",
             "who": "Grosjean/Sainz collide", "lap": 38, "type": "SC",
             "point": [837.0, 40.0],
             "source": "motorsport.com"},
            {"year": 2018, "corner": "1", "corner_label": "Turn 1 (Abbey)",
             "who": "Ericsson crashes", "lap": 32, "type": "SC",
             "point": [540.3, 588.9],
             "source": "lightsoutblog.com"},
            {"year": 2016, "corner": "1", "corner_label": "Turn 1 (Abbey)",
             "who": "Wehrlein aquaplanes", "lap": 7, "type": "VSC",
             "point": [540.3, 588.9],
             "source": "skysports.com"},
            {"year": 2014, "corner": "5", "corner_label": "Turn 5 (Aintree)",
             "who": "Räikkönen runs wide, crashes, collects Massa", "lap": 1,
             "type": "REDFLAG", "point": [860.5, 457.2],
             "source": "racefans.net / bleacherreport.com"},
        ],
        "incidents_note": ("This isn't every British GP incident since 2014, "
                            "only the ones public reporting let us confirm "
                            "cleanly enough to place at a specific corner. "
                            "Left off rather than guessed: 2019's Giovinazzi "
                            "spin (the actual Safety Car trigger that year) "
                            "came back with sources split between Vale and "
                            "Club; that same race's well-known Vettel/"
                            "Verstappen collision happened under green flag "
                            "after the restart, so it never triggered a "
                            "caution itself. 2020's three famous late-race "
                            "tyre failures (Bottas, Sainz, Hamilton) are "
                            "reported only relative to the pit entrance, "
                            "never a numbered corner. 2025's Hadjar/Antonelli "
                            "Safety Car-triggering crash was reported only as "
                            "happening 'in the spray,' with no corner named."),
    },

    "austin": {
        "name": "Circuit of the Americas",
        "location": "Austin, Texas, United States",
        "corners": 20,
        "length_km": 5.513,
        "view_box": [0, 0, 1000, 1000],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2022 United States Grand Prix
        # - Event Notes - Circuit Map v2" PDF, gridded and verified against
        # actual track-fill pixels, not label text -- this map's yellow
        # boxes are a separate "FIA Marshal Light No." sequence that
        # reuses the same digits as the real (blue) corner numbers and
        # sits right next to them in several places. The Turn 13-18
        # "snake" (a tight, alternating-direction complex distinct from
        # the Turn 3-9 esses) was traced pixel-by-pixel along the track
        # fill itself for exactly this reason. Verified 0 crossings.
        "points": [
            ("SF", 412.5, 941.5), ("1", 822.8, 929.9), ("2", 701.4, 836.0),
            ("3", 726.0, 688.7), ("4", 700.0, 633.8), ("5", 728.8, 570.2),
            ("6", 695.6, 509.5), ("7", 822.8, 454.6), ("8", 834.3, 344.8),
            ("9", 889.2, 353.5), ("10", 949.9, 261.0), ("11", 960.0, 40.0),
            ("12", 525.1, 547.1), ("13", 614.7, 613.5), ("14", 568.5, 645.3),
            ("15", 490.5, 633.8), ("16", 585.8, 685.8), ("17", 608.9, 740.7),
            ("18", 539.6, 807.1), ("19", 405.2, 784.0), ("20", 320.0, 931.4),
        ],
        "corner_labels": [
            ["1", 835, 945], ["2", 670, 846], ["3", 742, 688], ["4", 668, 634],
            ["5", 746, 570], ["6", 663, 505], ["7", 840, 450], ["8", 826, 325],
            ["9", 905, 358], ["10", 966, 258], ["11", 975, 30], ["12", 494, 545],
            ["13", 632, 600], ["14", 572, 622], ["15", 458, 633], ["16", 604, 690],
            ["17", 626, 745], ["18", 515, 822], ["19", 372, 780], ["20", 288, 918],
        ],
        "start_finish": {"x1": 397, "y1": 923, "x2": 428, "y2": 960,
                          "label_x": 433, "label_y": 968},
        # Turn 15 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint spanning over a decade (2014, 2025).
        "highlight_point": [490.5, 633.8],
        "headline": "Turn 15 has caused a real, named Safety Car or VSC "
                     "eleven years apart — 2014 and 2025.",
        "dek": ("Six real, named incidents since COTA's 2013 sophomore "
                "race, and the clearest repeat is Turn 15 — both times a "
                "driver misjudging a pass into the tightening left-hander: "
                "Sergio Pérez hit the back of Räikkönen and speared into "
                "Sutil there on the opening lap of 2014, and Carlos Sainz "
                "collided with Antonelli lunging for the same corner in "
                "2025. The other repeat is Turn 19, the fast downhill left "
                "before the final corner — Bottas (2022) and Hamilton "
                "(2024) were both beached in the gravel there by the same "
                "reported cause, a sudden gust of wind. 2022 is also the "
                "only USGP to need two separate Safety Cars in one race: "
                "Bottas's spin at Turn 19, then Alonso launched airborne "
                "into Stroll at Turn 12 four laps later."),
        "incidents": [
            {"year": 2025, "corner": "15", "corner_label": "Turn 15",
             "who": "Sainz collides with Antonelli", "lap": 7, "type": "VSC",
             "point": [490.5, 633.8],
             "source": "motorsport.com / racingnews365.com"},
            {"year": 2024, "corner": "19", "corner_label": "Turn 19",
             "who": "Hamilton spins into the gravel (wind gust)", "lap": 2,
             "type": "SC", "point": [405.2, 784.0],
             "source": "planetf1.com / racefans.net"},
            {"year": 2022, "corner": "19", "corner_label": "Turn 19",
             "who": "Bottas spins into the gravel (wind gust)", "lap": 18,
             "type": "SC", "point": [405.2, 784.0],
             "source": "thecheckeredflag.co.uk / racefans.net"},
            {"year": 2022, "corner": "12", "corner_label": "Turn 12",
             "who": "Alonso launched airborne into Stroll", "lap": 22,
             "type": "SC", "point": [525.1, 547.1],
             "source": "planetf1.com / motorsportmagazine.com"},
            {"year": 2014, "corner": "15", "corner_label": "Turn 15",
             "who": "Pérez hits Räikkönen, collects Sutil", "lap": 1,
             "type": "SC", "point": [490.5, 633.8],
             "source": "motorsportweek.com"},
            {"year": 2013, "corner": "straight", "corner_label": "Back straight",
             "who": "Sutil/Maldonado collide", "lap": 1, "type": "SC",
             "point": [742.5, 293.6],
             "source": "formula1.com / crash.net"},
        ],
        "incidents_note": ("Restricted to the Grand Prix itself -- the "
                            "2023-2025 Sprint races' own Safety Cars are a "
                            "separate session and excluded, the same "
                            "convention this file uses elsewhere. Also left "
                            "off rather than guessed: 2015's Ericsson "
                            "stoppage is real but sources conflict on the "
                            "exact corner ('after Turn 10' vs 'after Turn "
                            "11'); 2016's Verstappen and 2018's Ricciardo "
                            "retirements each triggered a VSC but were "
                            "reported only as 'trackside' with no corner "
                            "given; a 2021 VSC for track debris named "
                            "neither a driver nor a corner; Vettel's 2019 "
                            "Turn 9 suspension failure is well documented "
                            "but did not itself trigger a Safety Car or VSC "
                            "— he coasted off safely. The 2012 inaugural "
                            "race could not be confirmed to have had a "
                            "Safety Car at all from available sourcing."),
    },

    "mexico city": {
        "name": "Autódromo Hermanos Rodríguez",
        "location": "Mexico City, Mexico",
        "corners": 17,
        "length_km": 4.304,
        "view_box": [0, 0, 1000, 970],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2025 Mexico City Grand Prix -
        # Event Notes - Circuit Map" PDF, corner-number glyphs (blue)
        # distinguished from the separate red "Marshal Post" and yellow
        # "FIA Marshal Light" number sequences that share the same digits
        # on this map -- each snapped to the nearest actual track-edge
        # pixel, not the label's own position. The Foro Sol stadium
        # section (12-17, a tight S-curve into a hairpin) got a dedicated
        # fine-grid re-read before finalizing. Verified 0 crossings.
        "points": [
            ("SF", 320.0, 803.0), ("1", 441.7, 58.6), ("2", 493.2, 70.9),
            ("3", 509.7, 40.0), ("4", 881.0, 236.9), ("5", 911.8, 202.9),
            ("6", 960.2, 268.9), ("7", 764.4, 262.7), ("8", 717.9, 311.2),
            ("9", 670.5, 333.8), ("10", 645.8, 445.2), ("11", 590.1, 465.9),
            ("12", 513.8, 804.0), ("13", 412.8, 815.3), ("14", 410.7, 846.3),
            ("15", 408.7, 869.9), ("16", 398.4, 925.6), ("17", 320.0, 872.0),
        ],
        "corner_labels": [
            ["1", 415, 40], ["2", 505, 92], ["3", 520, 18], ["4", 872, 260],
            ["5", 922, 180], ["6", 980, 275], ["7", 745, 240], ["8", 735, 335],
            ["9", 645, 340], ["10", 668, 452], ["11", 566, 470], ["12", 530, 782],
            ["13", 425, 795], ["14", 434, 848], ["15", 432, 878], ["16", 400, 948],
            ["17", 336, 880],
        ],
        "start_finish": {"x1": 306, "y1": 787, "x2": 334, "y2": 819,
                          "label_x": 344, "label_y": 815},
        # Turn 1 is drawn as a highlighted ring on the page -- the repeat
        # flashpoint (4 named incidents across 2016/2018/2023/2024).
        "highlight_point": [441.7, 58.6],
        "headline": "Turn 1 has triggered a Safety Car or Virtual Safety "
                     "Car in 4 separate years — 2016, 2018, 2023 and 2024.",
        "dek": ("Eight real, named incidents since 2015, and the clearest "
                "repeat is Turn 1 — the very long, heavy-braking zone at "
                "the end of the pit straight, taken at some of the highest "
                "approach speeds of the year thanks to the circuit's "
                "altitude thinning the air. Wehrlein was punted off there "
                "at the first race back in 2016, Ricciardo's Red Bull went "
                "up in smoke on the outside of it in 2018, Leclerc's own "
                "front-wing endplate came off there in 2023, and Tsunoda "
                "and Albon wiped each other out there on the opening lap "
                "of 2024. The other repeat offender is Turn 2, right after "
                "it — Räikkönen and Magnussen's contact there in 2019, "
                "and Tsunoda beached there in the three-car pile-up (with "
                "Schumacher and Ocon) that opened 2021."),
        "incidents": [
            {"year": 2024, "corner": "1", "corner_label": "Turn 1",
             "who": "Tsunoda/Albon collide, both retire", "lap": 1, "type": "SC",
             "point": [441.7, 58.6],
             "source": "formula1.com / gpfans.com / racingnews365.com"},
            {"year": 2023, "corner": "9", "corner_label": "Turn 9",
             "who": "Magnussen crashes heavily, suspension failure", "lap": 33,
             "type": "REDFLAG", "point": [670.5, 333.8],
             "source": "en.wikipedia.org"},
            {"year": 2023, "corner": "1", "corner_label": "Turn 1",
             "who": "Leclerc's front-wing endplate breaks off", "lap": 5,
             "type": "VSC", "point": [441.7, 58.6],
             "source": "en.wikipedia.org"},
            {"year": 2021, "corner": "2", "corner_label": "Turn 2",
             "who": "Tsunoda/Schumacher collide (Ocon wedged between them)",
             "lap": 1, "type": "SC", "point": [493.2, 70.9],
             "source": "motorsportmagazine.com / espn.com"},
            {"year": 2019, "corner": "2", "corner_label": "Turn 2",
             "who": "Räikkönen/Magnussen contact, debris", "lap": 1,
             "type": "VSC", "point": [493.2, 70.9],
             "source": "en.wikipedia.org"},
            {"year": 2018, "corner": "1", "corner_label": "Turn 1",
             "who": "Ricciardo retires, hydraulic failure and smoke", "lap": 62,
             "type": "VSC", "point": [441.7, 58.6],
             "source": "grandprix.com / espn.com / abc.net.au"},
            {"year": 2016, "corner": "1", "corner_label": "Turn 1",
             "who": "Wehrlein punted off by a Sauber", "lap": 1, "type": "SC",
             "point": [441.7, 58.6],
             "source": "en.wikipedia.org"},
            {"year": 2015, "corner": "7", "corner_label": "Turn 7",
             "who": "Vettel spins, hits the barriers", "lap": 53, "type": "SC",
             "point": [764.4, 262.7],
             "source": "en.wikipedia.org"},
        ],
        "incidents_note": ("This isn't every Mexican GP incident since "
                            "2015, only the ones public reporting let us "
                            "confirm cleanly enough to place at a specific "
                            "corner. Left off rather than guessed: Sainz's "
                            "2018 retirement (sources disagree on both the "
                            "lap — 28 or 31 — and give no corroborated "
                            "corner); Alonso's 2022 retirement (lap number "
                            "conflicts between sources, no confirmed corner "
                            "or caution tie-in); Hartley's 2017 VSC (real, "
                            "but no corner given); Sainz's 2025 VSC "
                            "(reported only as 'trackside')."),
    },

    "singapore": {
        "name": "Marina Bay Street Circuit",
        "location": "Singapore",
        "corners": 19,
        "length_km": 4.927,
        "view_box": [0, 0, 1000, 718],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Geometry is the CURRENT layout only (raced 2023 onward, post the
        # reconfiguration that removed the old Turns 16-19 loop around the
        # Float at Marina Bay in favour of a straight, and renumbered the
        # old Turns 20-23 to the new Turns 16-19) -- read directly off the
        # official FIA "2025 Singapore Grand Prix - Event Notes - Circuit
        # Map" PDF (fia.com), gridded and verified (corner-number labels
        # isolated by color and cross-checked against a track-pixel mask).
        # Verified 0 crossings.
        "points": [
            ("SF", 916.3, 209.5), ("1", 804.1, 40.0), ("2", 771.2, 73.3),
            ("3", 723.0, 44.2), ("4", 746.8, 127.4), ("5", 835.2, 218.3),
            ("6", 641.3, 317.1), ("7", 453.9, 286.1), ("8", 431.2, 387.6),
            ("9", 356.6, 390.0), ("10", 320.0, 590.2), ("11", 407.8, 598.4),
            ("12", 421.3, 646.6), ("13", 510.6, 677.6), ("14", 465.9, 399.6),
            ("15", 574.6, 419.9), ("16", 792.7, 329.9), ("17", 820.1, 350.2),
            ("18", 922.4, 306.6), ("19", 970.0, 264.7),
        ],
        "corner_labels": [
            ["1", 815, 21], ["2", 781, 54], ["3", 730, 23], ["4", 757, 108],
            ["5", 854, 207], ["6", 651, 297], ["7", 433, 280], ["8", 410, 393],
            ["9", 335, 394], ["10", 303, 604], ["11", 393, 615], ["12", 409, 665],
            ["13", 503, 698], ["14", 445, 407], ["15", 562, 438], ["16", 815, 328],
            ["17", 842, 351], ["18", 944, 304], ["19", 991, 260],
        ],
        "start_finish": {"x1": 934, "y1": 196, "x2": 899, "y2": 223,
                          "label_x": 903, "label_y": 229},
        # Turn 1 is drawn as a highlighted ring -- the only corner with
        # more than one same-corner Safety Car in the modern-numbering era.
        "highlight_point": [804.1, 40.0],
        "headline": "Turn 1 has triggered a full Safety Car twice — a "
                     "first-lap pileup in 2017 and a suspension-breaking "
                     "clash in 2019 — and it's still the only corner at "
                     "Marina Bay with more than one Safety Car to its name "
                     "under the current numbering.",
        "dek": ("Turn 8 has its own smaller repeat: Grosjean clipped "
                "Russell into the wall there in 2019, and Albon hit it "
                "himself in 2022. What's NOT here matters as much as what "
                "is — Singapore renumbered its whole back section for "
                "2023, and the circuit's single most notorious corner, the "
                "old Turn 18 (four separate Safety Car-triggering crashes "
                "from 2008 to 2013, including Kobayashi and Ricciardo), no "
                "longer exists on this layout at all, replaced by a "
                "straight. And the streak that defined this race for a "
                "generation — a Safety Car in every single Singapore GP "
                "from 2008 through 2023 — broke in 2024 and stayed broken "
                "in 2025, both run caution-free."),
        "incidents": [
            {"year": 2022, "corner": "10", "corner_label": "Turn 10",
             "who": "Tsunoda crashes into the barrier", "lap": 36, "type": "SC",
             "point": [320.0, 590.2],
             "source": "en.wikipedia.org / racefans.net"},
            {"year": 2022, "corner": "8", "corner_label": "Turn 8",
             "who": "Albon hits the wall, loses front wing", "lap": 26,
             "type": "VSC", "point": [431.2, 387.6],
             "source": "gpfans.com / en.wikipedia.org"},
            {"year": 2022, "corner": "4", "corner_label": "Turn 4",
             "who": "Zhou and Latifi collide, both retire", "lap": 7,
             "type": "SC", "point": [746.8, 127.4],
             "source": "lightsoutblog.com / en.wikipedia.org"},
            {"year": 2019, "corner": "1", "corner_label": "Turn 1",
             "who": "Kvyat and Räikkönen collide, suspension broken", "lap": 50,
             "type": "SC", "point": [804.1, 40.0],
             "source": "en.wikipedia.org"},
            {"year": 2019, "corner": "8", "corner_label": "Turn 8",
             "who": "Grosjean clips Russell into the wall", "lap": 34,
             "type": "SC", "point": [431.2, 387.6],
             "source": "en.wikipedia.org"},
            {"year": 2018, "corner": "3", "corner_label": "Turn 3",
             "who": "Pérez and Ocon collide, Ocon into the wall", "lap": 1,
             "type": "SC", "point": [723.0, 44.2],
             "source": "racefans.net / autosport.com"},
            {"year": 2017, "corner": "1", "corner_label": "Turn 1",
             "who": "Vettel/Räikkönen/Verstappen chain-reaction pileup "
                    "(Alonso also collected)", "lap": 1, "type": "SC",
             "point": [804.1, 40.0],
             "source": "racefans.net / espn.co.uk / motorsport.com"},
            {"year": 2009, "corner": "14", "corner_label": "Turn 14",
             "who": "Sutil and Heidfeld collide, Heidfeld eliminated", "lap": 20,
             "type": "SC", "point": [465.9, 399.6],
             "source": "lightsoutblog.com / en.wikipedia.org"},
        ],
        "incidents_note": ("Restricted to the current 19-turn layout raced "
                            "since 2023 — Turns 1-15 are numbered "
                            "identically before and after that change, but "
                            "the old Turns 16-19 (which looped around the "
                            "Float at Marina Bay) were removed outright in "
                            "favour of a straight, and the old Turns 20-23 "
                            "were renumbered to the new Turns 16-19. That "
                            "renumbering excludes some real history from "
                            "this page rather than guessing it onto new "
                            "geometry: 2008's 'Crashgate' (Piquet Jr's "
                            "deliberate crash, old Turn 17, lap 15) and four "
                            "separate Safety Car-triggering crashes at the "
                            "old Turn 18 alone (Massa/Sutil 2008, Kobayashi/"
                            "Senna 2010, Karthikeyan 2012, Ricciardo 2013) "
                            "all happened on sections of track that no "
                            "longer exist. No incidents are placed on the "
                            "new Turns 16-19 (old 20-23) — none turned up "
                            "in public reporting with a confirmed corner "
                            "number for that section, before or after the "
                            "renumbering. Several other real cautions were "
                            "also left off for lacking a named corner in "
                            "public reporting rather than being guessed: "
                            "2010 (Liuzzi), 2011 (Schumacher), 2012 "
                            "(Schumacher/Vergne), 2014 (Pérez/Sutil), 2015 "
                            "(Massa/Hülkenberg, plus a track-intruder VSC), "
                            "2016 (Hülkenberg), 2019 (Pérez's oil leak), "
                            "2022's two engine-failure VSCs (Alonso, Ocon), "
                            "and 2023's two VSCs (Sargeant debris, Ocon "
                            "gearbox failure)."),
    },

    "las vegas": {
        "name": "Las Vegas Strip Circuit",
        "location": "Las Vegas, Nevada, USA",
        "corners": 17,
        "length_km": 6.201,
        "view_box": [0, 0, 1000, 1300],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2023 Las Vegas Grand Prix -
        # Event Notes - Circuit Map V3" PDF (fia.com), corner numbers
        # isolated by color (blue "Corner Numbers") -- this map has a
        # second, similarly placed yellow "FIA Marshal Light No." sequence
        # that sits right next to several real corners, easy to misread as
        # a corner number. Verified 0 crossings.
        "points": [
            ("SF", 831.7, 1163.0), ("1", 970.0, 1046.3), ("2", 917.7, 1005.6),
            ("3", 816.7, 1100.8), ("4", 763.7, 1001.9), ("5", 761.2, 484.8),
            ("6", 901.0, 457.6), ("7", 930.1, 350.5), ("8", 922.8, 316.0),
            ("9", 951.9, 265.1), ("10", 690.4, 230.6), ("11", 588.7, 81.8),
            ("12", 438.0, 40.0), ("13", 392.6, 437.6), ("14", 320.0, 1196.6),
            ("15", 370.8, 1218.4), ("16", 425.3, 1253.0), ("17", 806.6, 1225.6),
        ],
        "corner_labels": [
            ["1", 992, 1040], ["2", 917, 985], ["3", 792, 1108], ["4", 733, 1000],
            ["5", 733, 484], ["6", 927, 462], ["7–8", 958, 330], ["9", 980, 260],
            ["10", 686, 206], ["11", 588, 58], ["12", 408, 20], ["13", 364, 437],
            ["14", 290, 1197], ["15", 368, 1244], ["16", 425, 1279], ["17", 806, 1250],
        ],
        "start_finish": {"x1": 820.6, "y1": 1153.0, "x2": 842.8, "y2": 1173.0,
                          "label_x": 857, "label_y": 1186},
        # Turn 1 is drawn as a highlighted ring on the page -- the one
        # real repeat this young circuit has produced (2023 and 2025,
        # both on the opening lap).
        "highlight_point": [970.0, 1046.3],
        "headline": "Turn 1 has triggered a caution in 2 of Las Vegas's "
                     "first 3 races — both times on the opening lap.",
        "dek": ("Las Vegas has only run three Grands Prix since its "
                "chaotic 2023 debut, so this is a thin sample and it "
                "shows: the clearest thing in it is Turn 1, the tight "
                "right-hander off the pit straight, where a first-lap "
                "incident brought out a caution in both 2023 (Alonso "
                "spins and collects Bottas, Pérez and Sainz all tangle "
                "in the same bottleneck) and 2025 (Lawson, clipped by a "
                "moment involving Piastri and Russell, is damaged and "
                "pits under VSC). 2024 ran clean from start to finish — "
                "no Safety Car, VSC or red flag at all — the opposite "
                "extreme in the same tiny sample. The other named incident "
                "each year has been a green-flag racing collision rather "
                "than a repeat spot: Norris's heavy solo crash at Turn 11 "
                "in 2023, Verstappen and Russell colliding at Turn 12 "
                "fighting for the lead later that same race, and Albon "
                "clipping Hamilton's Ferrari near Turn 14 in 2025."),
        "incidents": [
            {"year": 2025, "corner": "14", "corner_label": "Turn 14",
             "who": "Albon clips Hamilton, front-wing debris", "lap": 16,
             "type": "VSC", "point": [320.0, 1196.6],
             "source": "racefans.net / athlonsports.com"},
            {"year": 2025, "corner": "1", "corner_label": "Turn 1",
             "who": "Lawson, damaged in Turn 1 collision with Piastri, pits",
             "lap": 2, "type": "VSC", "point": [970.0, 1046.3],
             "source": "en.wikipedia.org / nzherald.co.nz"},
            {"year": 2023, "corner": "12", "corner_label": "Turn 12",
             "who": "Verstappen/Russell collide fighting for position",
             "lap": 26, "type": "SC", "point": [438.0, 40.0],
             "source": "formula1.com / racefans.net / autosport.com"},
            {"year": 2023, "corner": "11", "corner_label": "Turn 11",
             "who": "Norris crashes heavily", "lap": 3, "type": "SC",
             "point": [588.7, 81.8],
             "source": "formula1.com / autosport.com"},
            {"year": 2023, "corner": "1", "corner_label": "Turn 1",
             "who": "Alonso spins, collects Bottas (Pérez/Sainz also tangle)",
             "lap": 1, "type": "VSC", "point": [970.0, 1046.3],
             "source": "gpfans.com / racefans.net"},
        ],
        "incidents_note": ("Las Vegas has only run three Grands Prix "
                            "(2023-2025) — 2026's race hasn't happened yet "
                            "as of this writing — so this is honestly a "
                            "thin sample, not a settled pattern. 2024 needed "
                            "no Safety Car, VSC or red flag at all. Left off "
                            "rather than guessed or miscategorized: the "
                            "infamous 2023 loose-drain-cover red flag that "
                            "wrecked Sainz's car happened in first practice, "
                            "not the race; a second loose-drain-cover red "
                            "flag (reported near Turn 17) happened in 2025 "
                            "qualifying, also not the race. Norris's 2023 "
                            "Turn 11 crash has minor corner ambiguity in "
                            "sourcing — every account agrees he lost "
                            "control at Turn 11, but the car came to rest "
                            "near Turn 12 after a second impact; Turn 11 is "
                            "used since that's where every source says "
                            "control was actually lost."),
    },

    "interlagos": {
        "name": "Autódromo José Carlos Pace",
        "location": "São Paulo, Brazil",
        "corners": 15,
        "length_km": 4.309,
        "view_box": [0, 0, 1000, 1100],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Read directly off the official FIA "2022 Brazilian Grand Prix -
        # Event Notes - Circuit Map, Pit Lane Drawing and Red Zone" PDF
        # (fia.com), gridded and read corner-by-corner off the actual
        # track-edge pixels. The map's blue corner numbers (1-15) were
        # kept carefully separate from its yellow "FIA Marshal Light
        # Number" boxes (a different, unrelated sequence). Verified 0
        # crossings.
        "points": [
            ("SF", 364.4, 724.4), ("1", 458.7, 1056.9), ("2", 558.2, 1001.7),
            ("3", 650.7, 1046.2), ("4", 960.0, 338.7), ("5", 824.9, 292.4),
            ("6", 540.4, 648.0), ("7", 417.8, 576.9), ("8", 355.6, 424.0),
            ("9", 504.9, 463.1), ("10", 419.6, 192.9), ("11", 576.0, 278.2),
            ("12", 736.0, 96.9), ("13", 636.4, 40.0), ("14", 398.2, 93.3),
            ("15", 320.0, 530.7),
        ],
        "corner_labels": [
            ["1", 468, 1076], ["2", 520, 965], ["3", 672, 1078],
            ["4", 978, 313], ["5", 845, 258], ["6", 520, 690],
            ["7", 388, 600], ["8", 322, 438], ["9", 530, 490],
            ["10", 398, 163], ["11", 606, 300], ["12", 762, 73],
            ["13", 636, 14], ["14", 383, 58], ["15", 288, 555],
        ],
        "start_finish": {"x1": 345, "y1": 719, "x2": 384, "y2": 730,
                          "label_x": 400, "label_y": 735},
        # Turn 1 (Senna S) is drawn as a highlighted ring -- the repeat
        # flashpoint (5 named incidents across 3 of the last 5 years,
        # twice needing two separate cautions in the very same race).
        "highlight_point": [458.7, 1056.9],
        "headline": "Turn 1 (Senna S) has caused a Safety Car, VSC or Red "
                     "Flag in 3 of the last 5 São Paulo Grands Prix — and "
                     "twice, in 2021 and again in 2025, it happened not "
                     "once but twice in the same race.",
        "dek": ("Twenty real, named incidents across Interlagos' rain-"
                "soaked history, and Turn 1 is the clearest repeat: "
                "Tsunoda/Stroll then Schumacher/Räikkönen both in 2021, "
                "Albon/Magnussen/Hülkenberg's lap-1 pileup in 2023, then "
                "Bortoleto/Stroll and Piastri/Antonelli/Leclerc both in "
                "2025. Turn 2, the Senna S exit, has its own spread across "
                "eras (2008, 2010, 2017). Curva do Sol (Turn 3) triggered "
                "two separate Safety Cars in the same 2003 race, and Turn 8 "
                "(Bico de Pato/Pinheirinho) has caught out a Ferrari or an "
                "Alpine-family car twice in three years — Ricciardo/"
                "Magnussen in 2022, Sainz in 2024. The pit straight itself "
                "is the other repeat offender, mostly in the rain: 1993 "
                "(one of the first Safety Cars of F1's modern era), 2003, "
                "2012 and three separate times in 2016's chaos-soaked "
                "restart-after-restart race."),
        "incidents": [
            {"year": 2025, "corner": "1", "corner_label": "Turn 1 (Senna S)",
             "who": "Piastri hits Antonelli, who ricochets into Leclerc",
             "lap": 8, "type": "VSC", "point": [458.7, 1056.9],
             "source": "formula1.com"},
            {"year": 2025, "corner": "1", "corner_label": "Turn 1 (Senna S)",
             "who": "Bortoleto crashes after contact with Stroll", "lap": 4,
             "type": "SC", "point": [458.7, 1056.9],
             "source": "formula1.com / en.wikipedia.org"},
            {"year": 2024, "corner": "8", "corner_label": "Turn 8",
             "who": "Sainz spins into the wall, aquaplaning", "lap": 39,
             "type": "SC", "point": [355.6, 424.0],
             "source": "motorsportweek.com"},
            {"year": 2024, "corner": "1", "corner_label": "Turn 1",
             "who": "Hülkenberg spins", "lap": 28, "type": "VSC",
             "point": [458.7, 1056.9], "source": "en.wikipedia.org"},
            {"year": 2023, "corner": "1", "corner_label": "Turn 1",
             "who": "Albon, Magnussen and Hülkenberg collide, tyre barrier "
                    "damaged", "lap": 1, "type": "REDFLAG",
             "point": [458.7, 1056.9],
             "source": "formula1.com / motorsport.com"},
            {"year": 2022, "corner": "8", "corner_label": "Turn 8",
             "who": "Ricciardo tips Magnussen into a spin, both retire",
             "lap": 1, "type": "SC", "point": [355.6, 424.0],
             "source": "formula1.com"},
            {"year": 2021, "corner": "1", "corner_label": "Turn 1",
             "who": "Schumacher hits Räikkönen's rear tyre on the restart",
             "lap": 12, "type": "VSC", "point": [458.7, 1056.9],
             "source": "formula1.com"},
            {"year": 2021, "corner": "1", "corner_label": "Turn 1",
             "who": "Tsunoda and Stroll collide, debris SC", "lap": 6,
             "type": "SC", "point": [458.7, 1056.9], "source": "formula1.com"},
            {"year": 2019, "corner": "straight",
             "corner_label": "Back straight (Reta Oposta)",
             "who": "Leclerc and Vettel, Ferrari teammates, collide fighting "
                    "each other", "lap": 66, "type": "SC",
             "point": [774.4, 763.2], "source": "en.wikipedia.org"},
            {"year": 2017, "corner": "2", "corner_label": "Turn 2 (Senna S)",
             "who": "Vandoorne hits Ricciardo; Grosjean and Ocon also "
                    "collide", "lap": 1, "type": "SC",
             "point": [558.2, 1001.7], "source": "gtplanet.net"},
            {"year": 2016, "corner": "straight", "corner_label": "Pit straight",
             "who": "Massa crashes near the pit entry", "lap": 49,
             "type": "SC", "point": [364.4, 724.4],
             "source": "en.wikipedia.org / lightsoutblog.com"},
            {"year": 2016, "corner": "straight", "corner_label": "Pit straight",
             "who": "Räikkönen spins and hits the wall in the rain",
             "lap": 19, "type": "REDFLAG", "point": [364.4, 724.4],
             "source": "en.wikipedia.org"},
            {"year": 2016, "corner": "straight", "corner_label": "Pit straight",
             "who": "Ericsson crashes", "lap": 13, "type": "SC",
             "point": [364.4, 724.4], "source": "en.wikipedia.org"},
            {"year": 2012, "corner": "straight",
             "corner_label": "Start/finish straight",
             "who": "di Resta crashes; race finishes behind the Safety Car",
             "lap": 68, "type": "SC", "point": [364.4, 724.4],
             "source": "en.wikipedia.org"},
            {"year": 2010, "corner": "2", "corner_label": "Turn 2 (Senna S)",
             "who": "Liuzzi's suspension fails, hits the barrier", "lap": 51,
             "type": "SC", "point": [558.2, 1001.7],
             "source": "en.wikipedia.org"},
            {"year": 2008, "corner": "2", "corner_label": "Turn 2 (Senna S)",
             "who": "Rosberg hits Coulthard into Nakajima; Piquet crashes at "
                    "the next corner", "lap": 1, "type": "SC",
             "point": [558.2, 1001.7], "source": "en.wikipedia.org"},
            {"year": 2003, "corner": "3", "corner_label": "Turn 3 (Curva do Sol)",
             "who": "Button crashes heavily into the barrier", "lap": 33,
             "type": "SC", "point": [650.7, 1046.2],
             "source": "en.wikipedia.org"},
            {"year": 2003, "corner": "3", "corner_label": "Turn 3 (Curva do Sol)",
             "who": "Schumacher aquaplanes, narrowly avoiding the recovery "
                    "crane", "lap": 27, "type": "SC",
             "point": [650.7, 1046.2], "source": "en.wikipedia.org"},
            {"year": 2003, "corner": "straight",
             "corner_label": "Start/finish straight",
             "who": "Firman's suspension fails, collects Panis at ~190mph",
             "lap": 18, "type": "SC", "point": [364.4, 724.4],
             "source": "en.wikipedia.org"},
            {"year": 1993, "corner": "straight",
             "corner_label": "Start/finish straight",
             "who": "Katayama and Suzuki crash in the rain -- one of the "
                    "first Safety Car deployments of F1's modern era",
             "lap": 27, "type": "SC", "point": [364.4, 724.4],
             "source": "en.wikipedia.org"},
        ],
        "incidents_note": ("This isn't every Brazilian/São Paulo GP caution "
                            "on record, only the ones public reporting let "
                            "us confirm at a specific corner. Left off "
                            "rather than guessed: 2024's Colapinto red-flag "
                            "crash, where one source says turns 13-14 but "
                            "every other outlet describes it as happening "
                            "climbing the hill onto the start-finish "
                            "straight (Turn 15) — a real conflict, not "
                            "just vagueness. Also excluded for lacking a "
                            "corner in any source: 2021's lap-30 Stroll "
                            "VSC, 2019's lap-52 Bottas SC, 2012's lap-23 "
                            "debris SC, and 2022's lap-53 Norris VSC/SC "
                            "(one source says Turn 10, nothing else "
                            "corroborates it). Sprint-only incidents (2024, "
                            "2025) are excluded, matching the convention "
                            "used elsewhere in this file."),
    },

    "madring": {
        "name": "Madring",
        "location": "Madrid, Spain",
        "corners": 22,
        "length_km": 5.414,
        "view_box": [0, 0, 1000, 480],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Madring debuted on the calendar in September 2026 (Spanish GP
        # moved here from Barcelona-Catalunya) -- no official FIA
        # circuit-map PDF could be located for it. Geometry instead read
        # directly off a vector circuit diagram on Wikimedia Commons
        # (File:Madring_Formula_1_Circuit.svg) that encodes both the track
        # outline AND a labeled apex marker with exact coordinates for
        # every numbered corner in the same coordinate space as the
        # outline -- verified by tracing each apex marker against the
        # outline path's own point list (not a freehand trace),
        # corroborated against independent prose (madring.com, Wikipedia):
        # "La Monumental" banked corner = Turn 12, "El Búnker" = Turn 8,
        # "Las Enlazadas de Valdebebas" = Turns 14-16, all matching where
        # those turns land here. Verified 0 self-intersections.
        "points": [
            ("SF", 364.6, 377.8), ("1", 338.7, 225.0), ("2", 321.2, 220.7),
            ("3", 320.0, 176.0), ("4", 529.0, 59.1), ("5", 605.6, 77.5),
            ("5a", 615.6, 71.7), ("6", 626.2, 76.4), ("7", 728.6, 40.0),
            ("8", 748.0, 53.7), ("9", 775.5, 41.9), ("10", 835.9, 42.2),
            ("11", 869.6, 70.0), ("12", 960.0, 95.1), ("13", 792.8, 66.4),
            ("14", 747.9, 114.9), ("15", 670.0, 133.6), ("16", 660.9, 195.9),
            ("17", 670.6, 218.8), ("18", 603.8, 263.6), ("19", 596.5, 331.6),
            ("20", 477.4, 363.4), ("20a", 482.4, 375.4), ("21", 486.6, 415.3),
            ("22", 382.2, 437.5),
        ],
        "corner_labels": [
            ["1", 358, 217], ["2", 308, 240], ["3", 305, 170], ["4", 529, 30],
            ["5", 590, 100], ["5a", 616, 46], ["6", 634, 100], ["7", 731, 14],
            ["8", 747, 78], ["9", 768, 16], ["10", 850, 20], ["11", 875, 92],
            ["12", 985, 96], ["13", 797, 90], ["14", 756, 140], ["15", 648, 125],
            ["16", 638, 202], ["17", 692, 226], ["18", 620, 281], ["19", 618, 341],
            ["20", 455, 358], ["20a", 510, 380], ["21", 508, 429], ["22", 378, 461],
        ],
        "start_finish": {"x1": 350, "y1": 363, "x2": 380, "y2": 393,
                          "label_x": 390, "label_y": 400},
        # Turn 20 is drawn as a highlighted ring on the page -- Madring's
        # ONLY named incident so far (one race run to date), not a repeat
        # pattern.
        "highlight_point": [477.4, 363.4],
        "headline": "Madring's debut Grand Prix needed one Virtual Safety "
                     "Car — too new to show a pattern yet.",
        "dek": ("Madring hosted its first Grand Prix in September 2026 "
                "(the Spanish GP's move from Barcelona-Catalunya), and "
                "exactly one race means there's no repeat-corner story to "
                "tell yet — just a single data point. That race needed "
                "one Virtual Safety Car: Lance Stroll's Aston Martin, "
                "brake failure into the wall at Turn 20, lap 14. Three "
                "other retirements that same race — Lewis Hamilton's own "
                "brake failure, a Sainz/Alonso collision at Turn 5, "
                "Sergio Pérez's water-system issue — didn't trigger any "
                "caution at all, so they're left off this list rather "
                "than force-fit in. Check back after a second Madrid GP."),
        "incidents": [
            {"year": 2026, "corner": "20", "corner_label": "Turn 20",
             "who": "Stroll crashes, brake failure", "lap": 14, "type": "VSC",
             "point": [477.4, 363.4],
             "source": "formula1.com / espn.com.au"},
        ],
        "incidents_note": ("Madring's entire Grand Prix history is one "
                            "race (September 2026), so this is necessarily "
                            "a single-incident list, not a curated subset "
                            "of a longer one — there's nothing else real "
                            "to add yet, and nothing was padded in to make "
                            "the page look more populated than it is. "
                            "Three other real retirements from that same "
                            "race (Hamilton's brake failure, a Sainz/Alonso "
                            "collision at Turn 5, Pérez's water-system "
                            "issue) are excluded because none of them "
                            "triggered a Safety Car, VSC, or red flag — "
                            "sources agree the race ran the rest of its "
                            "distance green. Multiple red flags did occur "
                            "during practice sessions that weekend, but "
                            "this dataset (matching every other circuit's "
                            "convention here) is race-only."),
    },

    "yas marina circuit": {
        "name": "Yas Marina Circuit",
        "location": "Abu Dhabi, United Arab Emirates",
        "corners": 16,
        "length_km": 5.281,
        "view_box": [0, 0, 1000, 1401],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Geometry is the CURRENT layout only (raced 2021 onward, post the
        # reconfiguration that merged the old Turns 4-6 into a single Turn
        # 5 hairpin, replaced the old Turns 11-14 marina/hotel section
        # with a sweeping banked curve, and opened up the old Turns
        # 18-20) -- read directly off the official FIA "2025 Abu Dhabi
        # Grand Prix - Event Notes - Circuit Map" PDF, using the PDF's own
        # vector text coordinates for each corner-number label (not a
        # pixel-grid guess), cross-checked against a gridded high-res
        # render. Verified 0 crossings.
        "points": [
            ("SF", 547.5, 765.1), ("1", 851.1, 751.0), ("2", 842.1, 555.2),
            ("3", 706.4, 467.0), ("4", 697.0, 319.1), ("5", 662.4, 40.0),
            ("6", 320.0, 929.2), ("7", 399.1, 910.8), ("8", 463.1, 1066.8),
            ("9", 960.0, 1361.0), ("10", 763.8, 1244.4), ("11", 678.3, 1186.8),
            ("12", 660.2, 1114.6), ("13", 713.3, 1061.6), ("14", 723.5, 964.2),
            ("15", 511.8, 972.7), ("16", 405.9, 823.1),
        ],
        "corner_labels": [
            ["1", 874, 739], ["2", 857, 534], ["3", 711, 441], ["4", 700, 293],
            ["5", 663, 14], ["6", 295, 935], ["7", 374, 917], ["8", 446, 1087],
            ["9", 974, 1383], ["10", 772, 1269], ["11", 681, 1213],
            ["12", 662, 1141], ["13", 722, 1086], ["14", 739, 985],
            ["15", 493, 990], ["16", 380, 820],
        ],
        "start_finish": {"x1": 544, "y1": 745, "x2": 551, "y2": 785,
                          "label_x": 558, "label_y": 792},
        # No highlight_point -- there's no genuine repeat-corner pattern in
        # the verified data (only one placeable race incident exists on
        # the current layout). Forcing a highlight ring on a single-
        # incident corner would overstate the pattern.
        "headline": "In five seasons on the current layout, Yas Marina "
                     "has produced exactly one Safety Car — and it's the "
                     "most consequential one in F1 history.",
        "dek": ("The 2021 reconfiguration remade the second half of the "
                "lap and, on the record since, also made this one of the "
                "hardest places on the calendar to bring out a Safety "
                "Car: 2022, 2023, 2024 and 2025 all ran start-to-finish "
                "without one. The exception is Turn 14, lap 53 of 2021 — "
                "Nicholas Latifi, fighting Mick Schumacher for 15th "
                "place, crashed there with dirty tyres after already "
                "running wide at Turn 9. The Safety Car that followed set "
                "up the late restart and Max Verstappen's title-deciding "
                "pass on Lewis Hamilton on the final lap. No other corner "
                "at Yas Marina has a second name attached to it since the "
                "layout changed."),
        "incidents": [
            {"year": 2021, "corner": "14", "corner_label": "Turn 14",
             "who": "Latifi crashes fighting Schumacher for 15th, dirty "
                    "tyres after running wide at Turn 9", "lap": 53,
             "type": "SC", "point": [723.5, 964.2],
             "source": "en.wikipedia.org"},
        ],
        "incidents_note": ("Restricted to the current 16-turn layout "
                            "raced since 2021 — the old 21-turn Yas "
                            "Marina (a separate Turns 4/5/6 sequence "
                            "merged into today's single Turn 5 hairpin, "
                            "and an entirely different marina/hotel "
                            "section in place of today's Turns 11-14) "
                            "doesn't map onto this geometry, so no "
                            "earlier incidents are placed here. Every "
                            "other 2021-2025 Abu Dhabi GP race (2022, "
                            "2023, 2024, 2025) ran completely "
                            "caution-free — checked directly against "
                            "each year's race report, not assumed. Three "
                            "other real, named incidents were left off: "
                            "Carlos Sainz's heavy Turn 3 crash red-flagged "
                            "FP2 in 2023 and Lewis Hamilton's Turn 9 crash "
                            "red-flagged FP3 in 2025 both happened in "
                            "practice, not the race; Antonio Giovinazzi's "
                            "VSC-triggering retirement on lap 35 of 2021 "
                            "is real but reporting only places it "
                            "'alongside the track' with no corner given, "
                            "so it was left off rather than guessed. Kimi "
                            "Räikkönen's career-ending crash at Turn 6 "
                            "(lap 26, 2021) is also real and corner-"
                            "specific but didn't itself trigger a Safety "
                            "Car, VSC or red flag, so it's outside this "
                            "page's scope."),
    },

    "lusail": {
        "name": "Lusail International Circuit",
        "location": "Lusail, Qatar",
        "corners": 16,
        "length_km": 5.419,
        "view_box": [0, 0, 1000, 570],
        # (label, x, y) -- "SF" is start/finish, others are corner numbers.
        # Geometry is the current 16-turn Grand Prix layout raced 2023
        # onward. No FIA circuit-map PDF could be reached this session
        # (search tooling failures, not a missing document) -- read
        # instead off Formula 1's own official media circuit-map image
        # (media.formula1.com, numbered 1-16, sector-colored), gridded at
        # 3x zoom per corner cluster, each point snapped to where the
        # colored centerline itself bends, not the label-bubble text
        # position. Same underlying source reliability as an FIA map
        # (F1's own official numbered diagram) but disclosed here as a
        # substitution, not literally the FIA document. Verified 0
        # crossings, including a specific re-check of the corner-dense
        # 4-9 double-apex middle sector.
        "points": [
            ("SF", 701.4, 525.2), ("1", 387.7, 528.3), ("2", 458.4, 398.1),
            ("3", 380.2, 319.1), ("4", 320.0, 131.0), ("5", 396.7, 92.7),
            ("6", 473.5, 228.8), ("7", 538.2, 40.0), ("8", 572.0, 116.0),
            ("9", 628.4, 170.2), ("10", 613.4, 283.0), ("11", 731.5, 258.9),
            ("12", 836.8, 70.8), ("13", 912.1, 68.6), ("14", 953.4, 185.2),
            ("15", 891.8, 292.8), ("16", 970.0, 514.7),
        ],
        "corner_labels": [
            ["1", 373, 545], ["2", 442, 412], ["3", 359, 325], ["4", 325, 108],
            ["5", 378, 81], ["6", 452, 226], ["7", 529, 20], ["8", 563, 96],
            ["9", 627, 148], ["10", 602, 302], ["11", 753, 261], ["12", 853, 56],
            ["13", 931, 57], ["14", 975, 181], ["15", 913, 297], ["16", 987, 528],
        ],
        "start_finish": {"x1": 690, "y1": 518, "x2": 713, "y2": 533,
                          "label_x": 701, "label_y": 505},
        # Turn 1 is drawn as a highlighted ring -- the only repeat
        # flashpoint this circuit's short history has produced (2023 and
        # 2025).
        "highlight_point": [387.7, 528.3],
        "headline": "Turn 1 has triggered a Safety Car in 2 of Lusail's "
                     "4 Grands Prix so far — both times a collision right "
                     "at the end of the long back straight.",
        "dek": ("Only two real Safety Cars are cleanly placeable at "
                "Lusail since its 2021 debut, and both are the same "
                "corner: Lewis Hamilton speared into George Russell at "
                "Turn 1 on the opening lap of 2023, breaking his own "
                "wheel hub and ending his race in the gravel; two years "
                "later Pierre Gasly ran into the side of Nico Hülkenberg "
                "as he tried to pass around the outside of the same "
                "corner, puncturing Hülkenberg's tyre. 2024 actually "
                "needed three separate Safety Cars — a lap-1 Hülkenberg/"
                "Colapinto/Ocon crash, a mirror-debris clearance from "
                "Albon's car, and a late Hülkenberg/Pérez spin — but no "
                "source ever named a corner for any of the three, so "
                "none is plotted here. 2021's debut race ran entirely "
                "green; its own story was four front-left tyre failures "
                "under one-stop strategies, not a caution."),
        "incidents": [
            {"year": 2025, "corner": "1", "corner_label": "Turn 1",
             "who": "Gasly runs into the side of Hülkenberg, who is "
                    "passing around the outside", "lap": 7, "type": "SC",
             "point": [387.7, 528.3],
             "source": "en.wikipedia.org"},
            {"year": 2023, "corner": "1", "corner_label": "Turn 1",
             "who": "Hamilton turns into Russell, breaks his wheel hub, "
                    "out on the spot", "lap": 1, "type": "SC",
             "point": [387.7, 528.3],
             "source": "en.wikipedia.org"},
        ],
        "incidents_note": ("Lusail has only run four real Grands Prix — "
                            "2022 was skipped from the calendar entirely "
                            "(not a missing data point), and 2021's debut "
                            "ran the whole race green (four front-left "
                            "tyre failures under green-flag one-stop "
                            "strategies, no Safety Car). 2024 is the real "
                            "gap: it's the one Lusail race with genuine "
                            "Safety Car drama (three separate "
                            "deployments), but no source reachable this "
                            "session named a specific corner for any of "
                            "the three incidents — left off rather than "
                            "guessed onto Turn 1 by pattern-matching "
                            "against 2023 and 2025. Sourcing on both "
                            "placed incidents also rests on a single "
                            "outlet (Wikipedia) rather than this file's "
                            "usual 2+-source standard, disclosed honestly "
                            "here rather than presented as equally solid "
                            "as the rest of this page."),
    },
}


# OpenF1 mislabels the second 2026 "Bahrain Grand Prix" (round 18) with
# circuit_short_name "Kuala Lumpur" -- it's the same real Sakhir circuit,
# not a distinct venue (see engine/predictor.py's SC_RATE_CIRCUIT comment),
# so it resolves to the existing "sakhir" entry rather than getting its own.
ALIASES = {"kuala lumpur": "sakhir"}


def get_circuit_guide(circuit: str) -> dict | None:
    """Static guide data for a circuit, or None if we don't have one yet.
    Deliberately a lookup, not a fallback/best-guess -- a circuit not in
    CIRCUITS means nobody has done the (manual, source-checked) research
    for it yet, not that it should render with placeholder data."""
    key = (circuit or "").lower()
    key = ALIASES.get(key, key)
    return CIRCUITS.get(key)
