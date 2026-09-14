"""
Unit tests for /api/races' podium/official_name additions and the new
/api/standings endpoint -- built for the front-page redesign's season
list (official weekend name + top-3 podium per race card) and
championship standings display.
"""
import api.routers.briefings as briefings


def _session(meeting_key, country, circuit, session_type, session_name,
            date_start, date_end):
    return {"meeting_key": meeting_key, "country_name": country,
            "circuit_short_name": circuit, "session_type": session_type,
            "session_name": session_name, "date_start": date_start,
            "date_end": date_end, "session_key": meeting_key * 100
            + {"Race": 1, "Sprint": 2}.get(session_name, 3)}


def _result(session_key, position, driver_number, points, gap=0):
    return {"session_key": session_key, "position": position,
            "driver_number": driver_number, "points": points,
            "gap_to_leader": gap, "dnf": False, "dsq": False}


class TestRaceListPodium:
    def _patch(self, monkeypatch, sessions, meetings, results_by_session, drivers_by_session):
        monkeypatch.setattr(briefings, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(briefings, "_cache_set", lambda *a, **k: None)

        def fake_get(endpoint, **params):
            if endpoint == "sessions":
                return sessions
            if endpoint == "meetings":
                return meetings
            if endpoint == "session_result":
                return results_by_session.get(params["session_key"], [])
            raise AssertionError(f"unexpected endpoint {endpoint}")

        monkeypatch.setattr(briefings, "_get", fake_get)
        monkeypatch.setattr(briefings, "get_drivers",
                            lambda sk, ttl: drivers_by_session.get(sk, {}))

    def test_race_gets_official_name_and_podium(self, monkeypatch):
        sessions = [_session(1, "China", "Shanghai", "Race", "Race",
                             "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00")]
        meetings = [{"meeting_key": 1, "meeting_official_name":
                    "FORMULA 1 HEINEKEN CHINESE GRAND PRIX 2026"}]
        sk = sessions[0]["session_key"]
        results = {sk: [_result(sk, 1, 12, 25.0), _result(sk, 2, 63, 18.0, 5.5),
                        _result(sk, 3, 44, 15.0, 25.3)]}
        drivers = {sk: {12: {"name_acronym": "ANT", "team_colour": "00D7B6"},
                       63: {"name_acronym": "RUS", "team_colour": "00D7B6"},
                       44: {"name_acronym": "HAM", "team_colour": "ED1131"}}}
        self._patch(monkeypatch, sessions, meetings, results, drivers)

        out = briefings.race_list(2026)
        race = out["races"][0]
        assert race["official_name"] == "FORMULA 1 HEINEKEN CHINESE GRAND PRIX 2026"
        assert len(race["podium"]) == 3
        assert race["podium"][0]["acronym"] == "ANT"
        assert race["podium"][1]["gap_to_leader"] == 5.5

    def test_sprint_session_has_no_podium(self, monkeypatch):
        sessions = [_session(1, "Miami", "Miami", "Race", "Sprint",
                             "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00")]
        meetings = [{"meeting_key": 1, "meeting_official_name": "FORMULA 1 MIAMI GP 2026"}]
        self._patch(monkeypatch, sessions, meetings, {}, {})
        out = briefings.race_list(2026)
        assert out["races"][0]["podium"] == []

    def test_sprint_and_race_same_weekend_merge_into_one_entry(self, monkeypatch):
        # Sprint Saturday, Grand Prix Sunday -- same meeting_key. A sprint
        # isn't a separate race weekend, so it should fold into the GP's
        # own entry rather than appear as a second card.
        sessions = [
            _session(1, "Miami", "Miami", "Race", "Sprint",
                    "2000-01-04T18:00:00+00:00", "2000-01-04T19:00:00+00:00"),
            _session(1, "Miami", "Miami", "Race", "Race",
                    "2000-01-05T19:00:00+00:00", "2000-01-05T21:00:00+00:00"),
        ]
        meetings = [{"meeting_key": 1, "meeting_official_name": "FORMULA 1 MIAMI GP 2026"}]
        self._patch(monkeypatch, sessions, meetings, {}, {})

        out = briefings.race_list(2026)
        assert len(out["races"]) == 1
        race = out["races"][0]
        assert race["session_name"] == "Race"
        assert race["sprint"] is not None
        assert race["sprint"]["session_key"] == sessions[0]["session_key"]

    def test_sprint_without_completed_gp_yet_stands_alone(self, monkeypatch):
        # Sprint has run but the Grand Prix itself hasn't finished (still
        # mid-weekend) -- nothing to fold into yet, so it surfaces on its own
        # rather than being dropped.
        sessions = [
            _session(1, "Miami", "Miami", "Race", "Sprint",
                    "2000-01-04T18:00:00+00:00", "2000-01-04T19:00:00+00:00"),
            _session(1, "Miami", "Miami", "Race", "Race",
                    "2099-01-05T19:00:00+00:00", "2099-01-05T21:00:00+00:00"),
        ]
        meetings = [{"meeting_key": 1, "meeting_official_name": "FORMULA 1 MIAMI GP 2026"}]
        self._patch(monkeypatch, sessions, meetings, {}, {})

        out = briefings.race_list(2026)
        assert len(out["races"]) == 1
        assert out["races"][0]["session_name"] == "Sprint"
        assert out["races"][0]["sprint"] is None

    def test_result_fetch_failure_yields_empty_podium_not_a_crash(self, monkeypatch):
        sessions = [_session(1, "China", "Shanghai", "Race", "Race",
                             "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00")]
        meetings = [{"meeting_key": 1, "meeting_official_name": "X"}]

        def fake_get(endpoint, **params):
            if endpoint == "sessions":
                return sessions
            if endpoint == "meetings":
                return meetings
            raise RuntimeError("429")

        monkeypatch.setattr(briefings, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(briefings, "_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(briefings, "_get", fake_get)
        monkeypatch.setattr(briefings, "get_drivers", lambda sk, ttl: {})

        out = briefings.race_list(2026)   # must not raise
        assert out["races"][0]["podium"] == []


class TestStandings:
    def _patch(self, monkeypatch, sessions, results_by_session, drivers_by_session):
        monkeypatch.setattr(briefings, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(briefings, "_cache_set", lambda *a, **k: None)

        def fake_get(endpoint, **params):
            if endpoint == "sessions":
                return sessions
            if endpoint == "session_result":
                return results_by_session.get(params["session_key"], [])
            raise AssertionError(f"unexpected endpoint {endpoint}")

        monkeypatch.setattr(briefings, "_get", fake_get)
        monkeypatch.setattr(briefings, "get_drivers",
                            lambda sk, ttl: drivers_by_session.get(sk, {}))

    def test_points_summed_across_multiple_races(self, monkeypatch):
        sessions = [
            _session(1, "China", "Shanghai", "Race", "Race",
                    "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00"),
            _session(2, "Japan", "Suzuka", "Race", "Race",
                    "2000-01-08T13:00:00+00:00", "2000-01-08T15:00:00+00:00"),
        ]
        sk1, sk2 = sessions[0]["session_key"], sessions[1]["session_key"]
        results = {
            sk1: [_result(sk1, 1, 12, 25.0), _result(sk1, 2, 63, 18.0)],
            sk2: [_result(sk2, 1, 63, 25.0), _result(sk2, 2, 12, 18.0)],
        }
        drivers = {
            sk1: {12: {"name_acronym": "ANT", "team_name": "Mercedes", "team_colour": "00D7B6"},
                 63: {"name_acronym": "RUS", "team_name": "Mercedes", "team_colour": "00D7B6"}},
            sk2: {12: {"name_acronym": "ANT", "team_name": "Mercedes", "team_colour": "00D7B6"},
                 63: {"name_acronym": "RUS", "team_name": "Mercedes", "team_colour": "00D7B6"}},
        }
        self._patch(monkeypatch, sessions, results, drivers)

        out = briefings.standings(2026)
        by_num = {d["driver_number"]: d for d in out["drivers"]}
        assert by_num[12]["points"] == 43.0   # ANT: 25 + 18
        assert by_num[63]["points"] == 43.0   # RUS: 18 + 25
        assert out["drivers"][0]["position"] == 1

    def test_constructor_points_credit_the_team_driven_for_that_race(self, monkeypatch):
        # A driver switching teams mid-season must credit each team only
        # for the points scored while actually driving for it.
        sessions = [
            _session(1, "China", "Shanghai", "Race", "Race",
                    "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00"),
            _session(2, "Japan", "Suzuka", "Race", "Race",
                    "2000-01-08T13:00:00+00:00", "2000-01-08T15:00:00+00:00"),
        ]
        sk1, sk2 = sessions[0]["session_key"], sessions[1]["session_key"]
        results = {
            sk1: [_result(sk1, 1, 99, 25.0)],
            sk2: [_result(sk2, 1, 99, 25.0)],
        }
        drivers = {
            sk1: {99: {"name_acronym": "SWP", "team_name": "Team A", "team_colour": "111111"}},
            sk2: {99: {"name_acronym": "SWP", "team_name": "Team B", "team_colour": "222222"}},
        }
        self._patch(monkeypatch, sessions, results, drivers)

        out = briefings.standings(2026)
        teams = {c["team"]: c["points"] for c in out["constructors"]}
        assert teams["Team A"] == 25.0
        assert teams["Team B"] == 25.0

    def test_zero_point_finish_does_not_crash_or_appear(self, monkeypatch):
        sessions = [_session(1, "China", "Shanghai", "Race", "Race",
                             "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00")]
        sk = sessions[0]["session_key"]
        results = {sk: [_result(sk, 15, 77, 0.0)]}
        drivers = {sk: {77: {"name_acronym": "ZZZ", "team_name": "Backmarker", "team_colour": "000"}}}
        self._patch(monkeypatch, sessions, results, drivers)

        out = briefings.standings(2026)
        assert out["drivers"] == []
        assert out["constructors"] == []
