import time

import pytest

from app.audit import Audit
from app.canonical import canon, hash_of
from app.store import Store


# ---------- canonical + audit ----------
def test_canonical_is_order_independent():
    assert canon({"b": 1, "a": 2}) == canon({"a": 2, "b": 1})
    assert hash_of({"a": 1}) != hash_of({"a": 2})


def test_audit_chain_detects_tampering():
    s = Store()
    a = Audit(s, time.time)
    for i in range(4):
        a.append("t", f"entry {i}", "d")
    assert a.verify() == {"ok": True, "checked": 4}
    s.run("UPDATE events SET plain='edited' WHERE seq=2")
    v = a.verify()
    assert v["ok"] is False and v["at"] == 2


def test_audit_chain_detects_deleted_entry():
    s = Store()
    a = Audit(s, time.time)
    for i in range(4):
        a.append("t", f"entry {i}")
    s.run("DELETE FROM events WHERE seq=2")
    assert a.verify()["ok"] is False


def test_transaction_rolls_back_on_error():
    s = Store()
    with pytest.raises(RuntimeError):
        with s.tx():
            s.run("INSERT INTO writes (idem, review_id, applied_at) VALUES ('x','g1',0)")
            raise RuntimeError("boom")
    assert s.one("SELECT 1 FROM writes") is None


