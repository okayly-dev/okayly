"""Reading and moving proposal rows. Every state move goes through move(), which enforces
the allowed transitions in core.domain."""
import json

from .domain import State, TRANSITIONS
from .errors import InvalidTransition, NotFound


def row(store, pid):
    r = store.one("SELECT * FROM proposals WHERE id=?", (pid,))
    if not r:
        raise NotFound(f"No proposal {pid}")
    return r


def view(r) -> dict:
    d = dict(r)
    d["before"] = json.loads(d.pop("before_json"))
    d["after"] = json.loads(d.pop("after_json"))
    d["first_draft"] = json.loads(d.pop("first_draft_json")) if d.get("first_draft_json") else None
    d["extra"] = json.loads(d.pop("extra_json")) if d.get("extra_json") else None
    d["handoff"] = bool(d["handoff"])
    return d


def move(store, pid: str, new: State, reason: str = "", **extra):
    with store.tx():
        r = row(store, pid)
        cur = State(r["state"])
        if new not in TRANSITIONS[cur]:
            raise InvalidTransition(f"{pid} cannot move from {cur.value} to {new.value}")
        sets, args = ["state=?", "reason=?"], [new.value, reason]
        for k, v in extra.items():
            sets.append(f"{k}=?")
            args.append(v)
        store.run(f"UPDATE proposals SET {', '.join(sets)} WHERE id=?", (*args, pid))


def live(store, kind: str, resource: str):
    return store.one(
        "SELECT * FROM proposals WHERE review_id=? AND kind=? AND state IN ('PROPOSED','APPROVED','EXECUTING','EXECUTED') "
        "ORDER BY created_at DESC LIMIT 1", (resource, kind))
