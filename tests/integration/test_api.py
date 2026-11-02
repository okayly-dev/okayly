import pytest

from fastapi.testclient import TestClient

from app.api import create_app
from app.wiring import build


def client(demo=True):
    return TestClient(create_app(build(db_path=":memory:", drafter="fixture"), demo_controls=demo))


@pytest.mark.parametrize("demo", [True, False])
def test_health_reports_demo_controls(demo):
    assert client(demo=demo).get("/api/health").json() == {
        "ok": True, "drafter": "FixtureDrafter", "demo_controls": demo,
    }


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
    assert c.post("/api/demo/reviews/g1/edit", json={}).status_code == 405
    assert c.post("/api/demo/audit/tamper", json={"on": True}).status_code == 405
    assert c.post("/api/demo/reset").status_code == 405


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


def test_ad_flow_over_http():
    c = client()
    assert c.get("/api/ads").json()["ads"][0]["status"] == "paused"
    p = c.post("/api/ads/propose", json={"name": "Spring new patients"}).json()
    assert p["state"] == "PROPOSED" and len(p["extra"]["candidates"]) == 3
    sha = p["after"]["image_sha"]
    img = c.get(f"/api/images/{sha}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert c.get("/api/images/" + "0" * 64).status_code == 404
    other = p["extra"]["candidates"][2]["sha"]
    p2 = c.post(f"/api/proposals/{p['id']}/picture", json={"sha": other}).json()
    assert p2["hash"] != p["hash"]
    bad = c.post(f"/api/proposals/{p['id']}/edit-ad", json={"headline": "Guaranteed results"})
    assert bad.status_code == 422
    assert c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]}).status_code == 409
    done = c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p2["hash"]}).json()
    assert done["state"] == "VERIFIED"
    assert [a["name"] for a in c.get("/api/ads").json()["ads"]][-1] == "Spring new patients"
    assert c.get("/api/audit/verify").json()["ok"] is True


def test_ad_name_collision_demo_control():
    c = client()
    p = c.post("/api/ads/propose", json={"name": "Teammate test"}).json()
    c.post("/api/demo/ads/collide", json={"name": "Teammate test"})
    out = c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]}).json()
    assert out["state"] == "FAILED" and out["reason"] == "precondition_changed"
    c.post("/api/demo/reset")
    assert len(c.get("/api/ads").json()["ads"]) == 1 and c.get("/api/ads").json()["proposals"] == []


def test_image_route_is_not_a_file_server():
    c = client()
    assert c.get("/api/images/../../etc/passwd").status_code in (404, 422)
    assert c.post("/api/proposals/x/picture", json={"sha": "../x"}).status_code == 422
