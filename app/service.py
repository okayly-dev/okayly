"""The orchestration core.

Muse proposes, code validates, a person approves, a separate executor writes, and an
independent read confirms. Every step is recorded in the audit chain in the same
transaction as the state change.

An approval is bound to the SHA-256 of the exact change. If the stored change differs from
what the approver saw, the approval is refused. If the world changed after approval, the
executor refuses to write."""
import json
import secrets
import time

from . import policy
from .audit import Audit
from .canonical import hash_of, sha256
from .domain import State, TRANSITIONS
from .errors import Expired, HashMismatch, InvalidTransition, NotFound, PolicyViolation
from .providers.sandbox import ManualHandoff

TTL_SECONDS = 24 * 3600


class Orchestrator:
    def __init__(self, store, providers: dict, drafter, facts: dict, past_replies: list[str], clock=time.time, ttl: int = TTL_SECONDS):
        self.store, self.providers, self.drafter = store, providers, drafter
        self.facts, self.past, self.clock, self.ttl = facts, past_replies, clock, ttl
        self.audit = Audit(store, clock)

    # ---- read-only context for the drafter: the only data Muse can reach ----
    def drafter_context(self):
        o = self

        class Context:
            def review(self, rid):
                return o._provider_for_review(rid).read_review(rid) if o._exists(rid) else None

            def facts(self):
                return o.facts

            def past_replies(self, n):
                return o.past[:n]
        return Context()

    # ---- helpers ----
    def _exists(self, rid):
        return self.store.one("SELECT 1 FROM reviews WHERE id=?", (rid,)) is not None

    def _provider_for_review(self, rid):
        r = self.store.one("SELECT platform FROM reviews WHERE id=?", (rid,))
        if not r:
            raise NotFound(f"No review {rid}")
        return self.providers[r["platform"]]

    def _row(self, pid):
        r = self.store.one("SELECT * FROM proposals WHERE id=?", (pid,))
        if not r:
            raise NotFound(f"No proposal {pid}")
        return r

    def _view(self, r) -> dict:
        d = dict(r)
        d["before"] = json.loads(d.pop("before_json"))
        d["after"] = json.loads(d.pop("after_json"))
        d["first_draft"] = json.loads(d.pop("first_draft_json")) if d.get("first_draft_json") else None
        d["handoff"] = bool(d["handoff"])
        return d

    @staticmethod
    def _payload(provider: str, review_id: str, before: dict, after: dict, attempt: int) -> dict:
        return {"env": "sandbox", "provider": provider, "kind": "reply", "resource": review_id,
                "operation": "post_review_reply", "before": before, "after": after, "attempt": attempt}

    def _move(self, pid: str, new: State, reason: str = "", **extra):
        with self.store.tx():
            r = self._row(pid)
            cur = State(r["state"])
            if new not in TRANSITIONS[cur]:
                raise InvalidTransition(f"{pid} cannot move from {cur.value} to {new.value}")
            sets, args = ["state=?", "reason=?"], [new.value, reason]
            for k, v in extra.items():
                sets.append(f"{k}=?")
                args.append(v)
            self.store.run(f"UPDATE proposals SET {', '.join(sets)} WHERE id=?", (*args, pid))

    # ---- propose ----
    def propose_reply(self, review_id: str) -> dict:
        provider = self._provider_for_review(review_id)
        rv = provider.read_review(review_id)
        live = self.store.one("SELECT * FROM proposals WHERE review_id=? AND state IN ('PROPOSED','APPROVED','EXECUTING','EXECUTED') ORDER BY created_at DESC LIMIT 1", (review_id,))
        if live:
            return self._view(live)
        if rv.reply is not None:
            raise InvalidTransition("This review already has a reply.")

        why = policy.needs_human(rv)
        if why:
            return self._skip(review_id, why)

        first_blocked = None
        d = self.drafter.draft(review_id)
        if d.escalate:
            return self._skip(review_id, d.escalate_reason or "A person should handle this one.")
        issues = policy.check_reply(d.reply, rv, self.facts)
        if issues:
            first_blocked = {"reply": d.reply, "issues": [i.message for i in issues]}
            self.audit.append("draft.blocked", "A first draft was stopped by the privacy and claims check.",
                              "; ".join(i.code for i in issues), None)
            d = self.drafter.draft(review_id, feedback=first_blocked)
            if d.escalate:
                return self._skip(review_id, d.escalate_reason or "A person should handle this one.")
            issues = policy.check_reply(d.reply, rv, self.facts)
            if issues:
                self.audit.append("draft.blocked_twice", "The rewrite was also stopped, so no reply was proposed.", "; ".join(i.code for i in issues), None)
                return self._skip(review_id, "We could not write a reply that passes the checks.", audit=False)

        attempt = 1 + (self.store.one("SELECT COALESCE(MAX(attempt),0) m FROM proposals WHERE review_id=?", (review_id,))["m"])
        before = {"text": rv.text, "reply": None}
        after = {"review": review_id, "platform": rv.platform, "reply": d.reply}
        h = hash_of(self._payload(provider.name, review_id, before, after, attempt))
        pid = "act_" + secrets.token_hex(4)
        now = self.clock()
        with self.store.tx():
            self.store.run(
                "INSERT INTO proposals (id, review_id, kind, state, reason, attempt, before_json, after_json, hash, idem, provider, handoff, priority, first_draft_json, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, review_id, "reply", State.PROPOSED.value, "", attempt, json.dumps(before), json.dumps(after), h,
                 "idem_" + sha256(h + str(attempt))[:12], provider.name, 0,
                 "personal_touch" if rv.stars <= 2 else "normal", json.dumps(first_blocked) if first_blocked else None, now, now + self.ttl),
            )
            self.audit.append("proposal.created", f"We drafted a reply to a {rv.stars}-star {rv.platform} review.",
                              f"hash {h[:12]}; attempt {attempt}; first draft blocked: {bool(first_blocked)}", pid)
        return self._view(self._row(pid))

    def _skip(self, review_id: str, reason: str, audit: bool = True) -> dict:
        if audit:
            self.audit.append("proposal.skipped", "We wrote no reply and left this review for a person.", reason, None)
        return {"status": "needs_human", "review_id": review_id, "reason": reason}

    # ---- edit ----
    def edit_reply(self, pid: str, text: str) -> dict:
        r = self._row(pid)
        if r["state"] != State.PROPOSED.value:
            raise InvalidTransition("Only a waiting reply can be edited.")
        rv = self._provider_for_review(r["review_id"]).read_review(r["review_id"])
        issues = policy.check_reply(text, rv, self.facts)
        if issues:
            raise PolicyViolation(issues)
        after = json.loads(r["after_json"])
        after["reply"] = text.strip()
        before = json.loads(r["before_json"])
        h = hash_of(self._payload(r["provider"], r["review_id"], before, after, r["attempt"]))
        with self.store.tx():
            self.store.run("UPDATE proposals SET after_json=?, hash=?, idem=? WHERE id=?",
                           (json.dumps(after), h, "idem_" + sha256(h + str(r["attempt"]))[:12], pid))
            self.audit.append("draft.edited", "You changed the wording of a reply. We checked it again and it passed.", f"hash {h[:12]}", pid)
        return self._view(self._row(pid))

    # ---- approve / reject ----
    def approve(self, pid: str, seen_hash: str, execute: bool = True) -> dict:
        r = self._row(pid)
        if r["state"] != State.PROPOSED.value:
            raise InvalidTransition(f"This reply is {r['state'].lower()}, so it cannot be approved.")
        if self.clock() > r["expires_at"]:
            self._move(pid, State.REJECTED, "expired")
            self.audit.append("approval.expired", "Your OK came too late, so nothing was done.", "", pid)
            raise Expired("This approval request expired.")
        if seen_hash != r["hash"]:
            self.audit.append("approval.refused", "Your OK was for a different version of this reply, so nothing was done.",
                              f"seen {seen_hash[:12]}, stored {r['hash'][:12]}", pid)
            raise HashMismatch("The reply changed after you looked at it. Please look again.")
        manual = not self.providers[self._platform(r)].can_post
        with self.store.tx():
            self._move(pid, State.APPROVED, "", handoff=int(manual))
            self.audit.append("action.approved", "You approved this reply.", f"bound to hash {r['hash'][:12]}", pid)
            if manual:
                self.audit.append("handoff.manual", "Nothing was posted. The platform does not allow it, so you paste the reply yourself.", "no read-back possible", pid)
        if manual or not execute:
            return self._view(self._row(pid))
        return self.execute(pid)

    def _platform(self, r) -> str:
        return json.loads(r["after_json"])["platform"]

    def reject(self, pid: str, reason: str) -> dict:
        self._move(pid, State.REJECTED, f"Reason: {reason}")
        self.audit.append("action.rejected", "You said not now to this reply.", reason, pid)
        return self._view(self._row(pid))

    # ---- execute and verify (separate from approval, and from Muse) ----
    def execute(self, pid: str) -> dict:
        r = self._row(pid)
        if r["state"] != State.APPROVED.value or r["handoff"]:
            raise InvalidTransition("Only an approved reply that this app can post can be executed.")
        after, before = json.loads(r["after_json"]), json.loads(r["before_json"])
        provider = self.providers[after["platform"]]
        self._move(pid, State.EXECUTING)
        self.audit.append("execution.started", "We are posting the reply now.", r["idem"], pid)
        cur = provider.read_review(r["review_id"])
        if cur is None or cur.reply is not None or cur.text != before["text"]:
            self._move(pid, State.FAILED, "precondition_changed")
            self.audit.append("execution.refused", "We stopped. The review changed after you said yes, so nothing was posted.", "precondition_changed; nothing written", pid)
            return self._view(self._row(pid))
        try:
            provider.post_reply(r["review_id"], after["reply"], r["idem"])
        except ManualHandoff:
            self._move(pid, State.FAILED, "manual_handoff_required")
            self.audit.append("execution.refused", "This platform does not allow posting from the app.", "manual_handoff_required", pid)
            return self._view(self._row(pid))
        self._move(pid, State.EXECUTED)
        self.audit.append("execution.succeeded", "We posted the reply.", "provider accepted write", pid)
        back = provider.read_review(r["review_id"])  # independent read, not the write response
        if back is not None and back.reply == after["reply"]:
            self._move(pid, State.VERIFIED)
            self.audit.append("verification.passed", "We looked at the review again. Your reply is showing.", "read-back equals expected", pid)
        else:
            self._move(pid, State.FAILED, "verification_mismatch")
            self.audit.append("verification.failed", "We checked and it did not match. Please look at it.", "read-back differs", pid)
        return self._view(self._row(pid))

    # ---- reads ----
    def get(self, pid: str) -> dict:
        return self._view(self._row(pid))

    def list_reviews(self) -> list[dict]:
        out = []
        for rv in self.providers["Google"].list_reviews():
            p = self.store.one("SELECT * FROM proposals WHERE review_id=? ORDER BY created_at DESC, attempt DESC LIMIT 1", (rv.id,))
            out.append({"review": rv.__dict__, "proposal": self._view(p) if p else None})
        return out

    def usage(self) -> dict:
        r = self.store.one("SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(cached_tokens),0) c, COALESCE(SUM(output_tokens),0) o, COALESCE(SUM(cost_usd),0) usd FROM usage")
        return {"calls": r["n"], "input_tokens": r["i"], "cached_tokens": r["c"], "output_tokens": r["o"], "cost_usd": round(r["usd"], 6)}
