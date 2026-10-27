from fastapi.testclient import TestClient

from app.api import create_app
from app.wiring import build


def client(demo=True):
    return TestClient(create_app(build(db_path=":memory:", drafter="fixture"), demo_controls=demo))


def test_full_flow_over_http():
    c = client()
    assert c.get("/api/health").json()["ok"]
    revs = c.get("/api/reviews").json()
    assert len(revs) == 7 and revs[0]["proposal"] is None
    p = c.post("/api/reviews/g2/propose").json()
    assert p["state"] == "PROPOSED"
    done = c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]}).json()
    assert done["state"] == "VERIFIED"
    assert c.get("/api/audit/verify").json()["ok"] is True
    assert len(c.get("/api/audit").json()) >= 5


def test_wrong_hash_is_409_and_bad_edit_is_422():
    c = client()
    p = c.post("/api/reviews/g2/propose").json()
    r = c.post(f"/api/proposals/{p['id']}/approve", json={"hash": "f" * 64})
    assert r.status_code == 409
    r = c.post(f"/api/proposals/{p['id']}/edit", json={"reply": "Sorry about your crown. We promise a refund."})
    assert r.status_code == 422 and {i["code"] for i in r.json()["issues"]} >= {"confirms_patient", "promise"}


def test_unknown_things_are_404_and_demo_controls_can_be_off():
    c = client(demo=False)
    assert c.get("/api/proposals/nope").status_code == 404
    assert c.post("/api/reviews/zzz/propose").status_code == 404
    assert c.post("/api/demo/reviews/g1/edit", json={}).status_code in (404, 405)  # route is not registered


def test_demo_edit_makes_the_executor_refuse():
    c = client()
    p = c.post("/api/reviews/g1/propose").json()
    c.post("/api/demo/reviews/g1/edit", json={})
    out = c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]}).json()
    assert out["state"] == "FAILED" and out["reason"] == "precondition_changed"


def test_needs_human_response_shape():
    r = client().post("/api/reviews/y3/propose").json()
    assert r["status"] == "needs_human" and "lawyer" in r["reason"]


def test_demo_reset_and_tamper_controls():
    c = client()
    p = c.post("/api/reviews/g2/propose").json()
    c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]})
    assert c.get("/api/audit/verify").json()["ok"] is True
    assert c.post("/api/demo/audit/tamper", json={"on": True}).json()["tampered"] is True
    v = c.get("/api/audit/verify").json()
    assert v["ok"] is False and v["at"] == 2
    assert c.post("/api/demo/audit/tamper", json={"on": False}).json()["tampered"] is False
    assert c.get("/api/audit/verify").json()["ok"] is True
    assert c.post("/api/demo/reset").json()["ok"] is True
    assert c.get("/api/audit").json() == []
    assert all(r["proposal"] is None for r in c.get("/api/reviews").json())
    assert c.post("/api/reviews/g2/propose").json()["state"] == "PROPOSED"


def test_skipped_review_is_audited_once():
    c = client()
    for _ in range(3):
        assert c.post("/api/reviews/y3/propose").json()["status"] == "needs_human"
    assert sum(1 for e in c.get("/api/audit").json() if e["type"] == "proposal.skipped") == 1
