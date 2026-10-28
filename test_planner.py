"""
Run with:  pip install pytest httpx   then   pytest -q
"""
import datetime as dt

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def make_request(**overrides):
    body = {
        "subjects": [
            {"name": "Java", "difficulty": 50, "preparation": 70, "exam_date": "2026-11-15", "topics": ["OOP", "Inheritance"]},
            {"name": "DBMS", "difficulty": 90, "preparation": 30, "exam_date": "2026-11-15", "topics": ["SQL", "Transactions"]},
            {"name": "OS", "difficulty": "Medium", "preparation": 50, "exam_date": "2026-11-15", "topics": []},
        ],
        "available_hours_per_day": 3,
        "study_start_time": "18:00",
        "session_duration": 45,
        "break_duration": 10,
        "available_days": ALL_DAYS,
        "start_date": "2026-10-26",
    }
    body.update(overrides)
    return body


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def test_plan_is_valid_and_has_no_overlaps():
    r = client.post("/generate-study-plan", json=make_request())
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["total_sessions"] == len(plan["sessions"]) > 0
    for day in plan["daily_timetable"]:
        assert day["total_minutes"] <= 3 * 60                       # respects daily hours
        times = sorted((to_min(s["start_time"]), to_min(s["end_time"])) for s in day["sessions"])
        assert times[0][0] >= to_min("18:00")                       # respects start time
        for (_, end), (next_start, _) in zip(times, times[1:]):
            assert next_start >= end + 10                           # no overlap, break kept


def test_no_session_on_or_after_exam_date():
    r = client.post("/generate-study-plan", json=make_request())
    for s in r.json()["plan"]["sessions"]:
        assert s["date"] < "2026-11-15"


def test_harder_and_less_prepared_subject_gets_more_time():
    r = client.post("/generate-study-plan", json=make_request())
    minutes = {x["subject"]: x["allocated_minutes"] for x in r.json()["plan"]["subject_summary"]}
    assert minutes["DBMS"] > minutes["OS"] > minutes["Java"]


def test_revision_sessions_exist_and_come_last():
    r = client.post("/generate-study-plan", json=make_request())
    sessions = [s for s in r.json()["plan"]["sessions"] if s["subject"] == "DBMS"]
    kinds = [s["session_type"] for s in sessions]
    assert "revision" in kinds
    assert kinds[-1] == "revision"                                  # revision is at the end
    first_rev = kinds.index("revision")
    assert all(k == "revision" for k in kinds[first_rev:])          # study never comes after revision


def test_respects_selected_days():
    r = client.post("/generate-study-plan", json=make_request(available_days=["monday", "Wed"]))
    assert r.status_code == 200
    assert {s["day"] for s in r.json()["plan"]["sessions"]} <= {"Monday", "Wednesday"}


def test_multiple_exam_dates():
    body = make_request()
    body["subjects"][1]["exam_date"] = "2026-11-02"
    r = client.post("/generate-study-plan", json=body)
    assert r.status_code == 200
    for s in r.json()["plan"]["sessions"]:
        if s["subject"] == "DBMS":
            assert s["date"] < "2026-11-02"


def test_insufficient_time_gives_warnings():
    body = make_request(start_date="2026-11-13", available_hours_per_day=1)
    r = client.post("/generate-study-plan", json=body)
    assert r.status_code == 200
    assert r.json()["warnings"]


def test_weekly_timetable_matches_daily():
    plan = client.post("/generate-study-plan", json=make_request()).json()["plan"]
    assert sum(w["total_minutes"] for w in plan["weekly_timetable"]) == plan["total_study_minutes"]
    assert all(w["week_start"] <= d["date"] <= w["week_end"] for w in plan["weekly_timetable"] for d in w["days"])


def test_exam_in_the_past_is_rejected():
    body = make_request()
    body["subjects"][0]["exam_date"] = "2020-01-01"
    r = client.post("/generate-study-plan", json=body)
    assert r.status_code == 422 and r.json()["status"] == "error"


def test_invalid_inputs_are_rejected():
    assert client.post("/generate-study-plan", json=make_request(subjects=[])).status_code == 422
    assert client.post("/generate-study-plan", json=make_request(available_hours_per_day=0)).status_code == 422
    assert client.post("/generate-study-plan", json=make_request(session_duration=240)).status_code == 422
    assert client.post("/generate-study-plan", json=make_request(available_days=["Funday"])).status_code == 422
    bad = make_request()
    bad["subjects"][0]["preparation"] = 150
    assert client.post("/generate-study-plan", json=bad).status_code == 422
    bad = make_request()
    bad["subjects"][0]["difficulty"] = "Impossible"
    assert client.post("/generate-study-plan", json=bad).status_code == 422


def test_session_that_does_not_fit_before_midnight():
    r = client.post("/generate-study-plan", json=make_request(study_start_time="23:50"))
    assert r.status_code == 422 and "midnight" in r.json()["message"]


def test_health_and_cors_headers():
    assert client.get("/health").json() == {"status": "ok"}
    r = client.options(
        "/generate-study-plan",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "*"
