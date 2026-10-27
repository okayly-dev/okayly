"""Append-only, hash-chained audit log. Each entry stores the SHA-256 of the one before it,
so changing history is detectable. Entries are written in the same transaction as the
state change they describe."""
import datetime as dt

from .canonical import canon, sha256

GENESIS = "0" * 64


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Audit:
    def __init__(self, store, clock):
        self.store = store
        self.clock = clock

    def append(self, type: str, plain: str, detail: str = "", proposal_id: str | None = None) -> int:
        with self.store.tx():
            last = self.store.one("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1")
            prev = last["hash"] if last else GENESIS
            seq = (last["seq"] if last else 0) + 1
            ts = _iso(self.clock())
            payload = canon({"type": type, "plain": plain, "detail": detail, "proposal_id": proposal_id})
            h = sha256(f"{prev}|{seq}|{ts}|{payload}")
            self.store.run(
                "INSERT INTO events (seq, ts, type, plain, detail, proposal_id, prev, hash) VALUES (?,?,?,?,?,?,?,?)",
                (seq, ts, type, plain, detail, proposal_id, prev, h),
            )
            return seq

    def events(self, limit: int = 200):
        rows = self.store.all("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def verify(self) -> dict:
        prev = GENESIS
        n = 0
        for r in self.store.all("SELECT * FROM events ORDER BY seq"):
            payload = canon({"type": r["type"], "plain": r["plain"], "detail": r["detail"], "proposal_id": r["proposal_id"]})
            if r["prev"] != prev or sha256(f"{prev}|{r['seq']}|{r['ts']}|{payload}") != r["hash"]:
                return {"ok": False, "at": r["seq"], "checked": n}
            prev = r["hash"]
            n += 1
        return {"ok": True, "checked": n}
