"""The orchestration core.

Muse proposes, code validates, a person approves, a separate executor writes, and an
independent read confirms. Every step is recorded in the audit chain in the same
transaction as the state change.

An approval is bound to the SHA-256 of the exact change. If the stored change differs from
what the approver saw, the approval is refused. If the world changed after approval, the
executor refuses to write.

Two kinds of change share this pipeline: a review reply and a paused ad draft."""
import hashlib
import json
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

from .verification import policy
from .core.audit import Audit
from .core.canonical import hash_of, sha256
from .core.domain import Issue, State, TRANSITIONS
from .core.errors import Expired, HashMismatch, InvalidTransition, NotFound, PolicyViolation
from .providers.sandbox import ManualHandoff, NameTaken

TTL_SECONDS = 24 * 3600

# The words the audit log and the interface use for each kind of change.
MSG = {
    "reply": dict(noun="reply", approved="You approved this reply.", rejected="You said not now to this reply.",
                  start="We are posting the reply now.",
                  refused="We stopped. The review changed after you said yes, so nothing was posted.",
                  done="We posted the reply.", detail_done="provider accepted write",
                  ok="We looked at the review again. Your reply is showing.",
                  bad="We checked and it did not match. Please look at it."),
    "ad": dict(noun="ad draft", approved="You approved this ad draft.", rejected="You said not now to this ad draft.",
               start="We are saving the ad as a paused draft.",
               refused="We stopped. Something changed after you said yes, so nothing was saved.",
               done="We saved the ad as a paused draft. It is not running.", detail_done="provider accepted write; status paused",
               ok="We looked at the ad again. It is saved, paused, and matches what you approved.",
               bad="We checked and the saved ad did not match. Please look at it."),
}
AD_NAME_MAX = 60


class Orchestrator:
    def __init__(self, store, providers: dict, drafter, facts: dict, past_replies: list[str], clock=time.time, ttl: int = TTL_SECONDS,
                 ad_studio=None):
        self.store, self.providers, self.drafter, self.ad_studio = store, providers, drafter, ad_studio
        self.facts, self.past, self.clock, self.ttl = facts, past_replies, clock, ttl
        self.audit = Audit(store, clock)

    # ---- read-only context for Muse: the only data it can reach ----
    def drafter_context(self):
        o = self

        class Context:
            def review(self, rid):
                return o._provider_for_review(rid).read_review(rid) if o._exists(rid) else None

            def facts(self):
                return o.facts

            def past_replies(self, n):
                return o.past[:n]

            def ad_rules(self):
                return policy.AD_RULES_TEXT
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
        d["extra"] = json.loads(d.pop("extra_json")) if d.get("extra_json") else None
        d["handoff"] = bool(d["handoff"])
        return d

    @staticmethod
    def _payload(kind: str, provider: str, resource: str, before: dict, after: dict, attempt: int) -> dict:
        if kind == "ad":
            return {"env": "sandbox", "provider": provider, "kind": "ad", "resource": resource,
                    "operation": "create_paused_ad_draft", "before": before, "after": after, "attempt": attempt,
                    "currency": "USD", "spend_usd": 0}
        return {"env": "sandbox", "provider": provider, "kind": "reply", "resource": resource,
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

    def _live(self, kind: str, resource: str):
        return self.store.one(
            "SELECT * FROM proposals WHERE review_id=? AND kind=? AND state IN ('PROPOSED','APPROVED','EXECUTING','EXECUTED') "
            "ORDER BY created_at DESC LIMIT 1", (resource, kind))

    def _create(self, *, kind, resource, provider, before, after, handoff, priority, first_blocked, extra, plain, detail, audits=()) -> dict:
        attempt = 1 + self.store.one("SELECT COALESCE(MAX(attempt),0) m FROM proposals WHERE review_id=? AND kind=?", (resource, kind))["m"]
        h = hash_of(self._payload(kind, provider, resource, before, after, attempt))
        pid = "act_" + secrets.token_hex(4)
        now = self.clock()
        with self.store.tx():
            self.store.run(
                "INSERT INTO proposals (id, review_id, kind, state, reason, attempt, before_json, after_json, hash, idem, provider, handoff, priority, first_draft_json, created_at, expires_at, extra_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, resource, kind, State.PROPOSED.value, "", attempt, json.dumps(before), json.dumps(after), h,
                 "idem_" + sha256(h + str(attempt))[:12], provider, handoff, priority,
                 json.dumps(first_blocked) if first_blocked else None, now, now + self.ttl,
                 json.dumps(extra) if extra else None))
            self.audit.append("proposal.created", plain, f"hash {h[:12]}; attempt {attempt}; first draft blocked: {bool(first_blocked)}" + detail, pid)
            for a in audits:
                self.audit.append(*a, pid)
        return self._view(self._row(pid))

    def _rehash(self, r, after: dict, type: str, plain: str) -> dict:
        h = hash_of(self._payload(r["kind"], r["provider"], r["review_id"], json.loads(r["before_json"]), after, r["attempt"]))
        with self.store.tx():
            self.store.run("UPDATE proposals SET after_json=?, hash=?, idem=? WHERE id=?",
                           (json.dumps(after), h, "idem_" + sha256(h + str(r["attempt"]))[:12], r["id"]))
            self.audit.append(type, plain, f"hash {h[:12]}", r["id"])
        return self._view(self._row(r["id"]))

    def _need(self, pid: str, kind: str):
        r = self._row(pid)
        if r["kind"] != kind:
            raise InvalidTransition(f"{pid} is not a {MSG[kind]['noun']}.")
        if r["state"] != State.PROPOSED.value:
            raise InvalidTransition(f"Only a waiting {MSG[kind]['noun']} can be edited.")
        return r

    # ---- propose a review reply ----
    def propose_reply(self, review_id: str) -> dict:
        provider = self._provider_for_review(review_id)
        rv = provider.read_review(review_id)
        live = self._live("reply", review_id)
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

        return self._create(
            kind="reply", resource=review_id, provider=provider.name,
            before={"text": rv.text, "reply": None}, after={"review": review_id, "platform": rv.platform, "reply": d.reply},
            handoff=0, priority="personal_touch" if rv.stars <= 2 else "normal", first_blocked=first_blocked, extra=None,
            plain=f"We drafted a reply to a {rv.stars}-star {rv.platform} review.", detail="")

    def _skip(self, resource: str, reason: str, audit: bool = True, what: str = "reply") -> dict:
        detail = f"{resource}: {reason}"
        if audit and not self.store.one("SELECT 1 FROM events WHERE type='proposal.skipped' AND detail=?", (detail,)):
            self.audit.append("proposal.skipped", f"We wrote no {what} and left this for a person.", detail, None)
        return {"status": "needs_human", "review_id": resource, "reason": reason}

    # ---- propose a paused ad draft ----
    def propose_ad(self, name: str, fmt: str = "wide") -> dict:
        name = (name or "").strip()
        if not 1 <= len(name) <= AD_NAME_MAX or not re.fullmatch(r"[\w .,'&()\-]+", name):
            raise PolicyViolation([Issue("bad_name", f"Give the ad a short name (up to {AD_NAME_MAX} letters, numbers and spaces).")])
        if fmt not in policy.AD_FORMATS:
            raise PolicyViolation([Issue("bad_format", "Pick wide, square or tall.")])
        live = self._live("ad", name)
        if live:
            return self._view(live)
        ads = self.providers["Ads"]
        if ads.read_ad(name) is not None:
            raise InvalidTransition("An ad with this name already exists.")

        first_blocked = None
        d = self.ad_studio.draft(name)
        issues = policy.check_ad(d.headline, d.text, self.facts)
        if issues:
            first_blocked = {"headline": d.headline, "text": d.text, "issues": [i.message for i in issues]}
            self.audit.append("draft.blocked", "A first ad draft was stopped by the ad rules check.", "; ".join(i.code for i in issues), None)
            d = self.ad_studio.draft(name, feedback=first_blocked)
            issues = policy.check_ad(d.headline, d.text, self.facts)
            if issues:
                self.audit.append("draft.blocked_twice", "The rewrite was also stopped, so no ad was proposed.", "; ".join(i.code for i in issues), None)
                return self._skip(name, "We could not write an ad that passes the checks.", audit=False, what="ad")

        pictures = self._make_pictures(d.image_prompts)
        passing = [p for p in pictures if p["passed"]]
        if not passing:
            self.audit.append("ad.no_picture", "No picture passed the picture check, so no ad was proposed.",
                              "; ".join(f"{p['sha'][:12] if p['sha'] else 'none'}: {','.join(p['codes'])}" for p in pictures), None)
            return self._skip(name, "None of the pictures passed the picture check.", audit=False, what="ad")

        with self.store.tx():   # pictures and proposal land together, or not at all
            for p in pictures:
                if p["data"]:
                    self.store.run("INSERT OR IGNORE INTO images (sha, mime, data, prompt, review_json, passed) VALUES (?,?,?,?,?,?)",
                                   (p["sha"], p["mime"], p["data"], p["prompt"], json.dumps(p["review"]), int(p["passed"])))
            cands = [{k: p[k] for k in ("sha", "mime", "prompt", "review", "passed", "issues")} for p in pictures]
            audits = [("image.checked", f"Picture {i + 1} passed the picture check." if p["passed"]
                       else f"Picture {i + 1} was stopped by the picture check: {' '.join(p['issues'])}",
                       (p["sha"] or "no picture")[:12] + "; " + (",".join(p["codes"]) or "all checks passed"))
                      for i, p in enumerate(pictures)]
            return self._create(
                kind="ad", resource=name, provider=ads.name, before={"exists": False},
                after={"name": name, "headline": d.headline, "text": d.text, "image_sha": passing[0]["sha"], "format": fmt, "status": "paused"},
                handoff=0, priority="normal", first_blocked=first_blocked, extra={"candidates": cands},
                plain=f"We drafted an ad called {name}. It will be saved paused, with no budget.",
                detail=f"; {len(passing)} of {len(pictures)} pictures passed", audits=audits)

    def _make_pictures(self, prompts: list[str]) -> list[dict]:
        """Make and check each picture in parallel. One failed picture does not stop the others."""
        def one(prompt):
            p = {"prompt": prompt, "sha": None, "mime": None, "data": None, "review": None, "passed": False, "issues": [], "codes": []}
            try:
                data = self.ad_studio.image(prompt)
                p.update(data=data, sha=hashlib.sha256(data).hexdigest(), mime=policy.sniff_image(data))
                p["review"] = self.ad_studio.review_image(data) if p["mime"] else None
                found = policy.check_image(data, p["review"])
            except Exception as e:   # a network or model failure becomes "this picture is not usable"
                found = [Issue("picture_failed", "We could not make or check this picture.")]
                p["error"] = type(e).__name__
            p.update(passed=not found, issues=[i.message for i in found], codes=[i.code for i in found])
            return p
        with ThreadPoolExecutor(max_workers=max(1, len(prompts))) as ex:
            return list(ex.map(one, prompts))

    # ---- edit ----
    def edit_reply(self, pid: str, text: str) -> dict:
        r = self._need(pid, "reply")
        rv = self._provider_for_review(r["review_id"]).read_review(r["review_id"])
        issues = policy.check_reply(text, rv, self.facts)
        if issues:
            raise PolicyViolation(issues)
        after = json.loads(r["after_json"])
        after["reply"] = text.strip()
        return self._rehash(r, after, "draft.edited", "You changed the wording of a reply. We checked it again and it passed.")

    def edit_ad(self, pid: str, headline: str | None = None, text: str | None = None, fmt: str | None = None) -> dict:
        r = self._need(pid, "ad")
        after = json.loads(r["after_json"])
        after["headline"] = (headline if headline is not None else after["headline"]).strip()
        after["text"] = (text if text is not None else after["text"]).strip()
        if fmt is not None:
            if fmt not in policy.AD_FORMATS:
                raise PolicyViolation([Issue("bad_format", "Pick wide, square or tall.")])
            after["format"] = fmt
        issues = policy.check_ad(after["headline"], after["text"], self.facts)
        if issues:
            raise PolicyViolation(issues)
        return self._rehash(r, after, "draft.edited", "You changed the wording of an ad. We checked it again and it passed.")

    def choose_picture(self, pid: str, sha: str) -> dict:
        r = self._need(pid, "ad")
        cands = (json.loads(r["extra_json"]) or {}).get("candidates", [])
        pick = next((c for c in cands if c["sha"] == sha), None)
        if pick is None:
            raise NotFound("That picture is not one of this ad's pictures.")
        if not pick["passed"]:
            raise PolicyViolation([Issue("picture_blocked", "That picture did not pass the picture check, so it cannot be used.")])
        after = json.loads(r["after_json"])
        after["image_sha"] = sha
        return self._rehash(r, after, "picture.chosen", "You picked a different picture for the ad.")

    # ---- approve / reject ----
    def approve(self, pid: str, seen_hash: str, execute: bool = True) -> dict:
        r = self._row(pid)
        m = MSG[r["kind"]]
        if r["state"] != State.PROPOSED.value:
            raise InvalidTransition(f"This {m['noun']} is {r['state'].lower()}, so it cannot be approved.")
        if self.clock() > r["expires_at"]:
            self._move(pid, State.REJECTED, "expired")
            self.audit.append("approval.expired", "Your OK came too late, so nothing was done.", "", pid)
            raise Expired("This approval request expired.")
        if seen_hash != r["hash"]:
            self.audit.append("approval.refused", f"Your OK was for a different version of this {m['noun']}, so nothing was done.",
                              f"seen {seen_hash[:12]}, stored {r['hash'][:12]}", pid)
            raise HashMismatch(f"The {m['noun']} changed after you looked at it. Please look again.")
        manual = r["kind"] == "reply" and not self.providers[self._platform(r)].can_post
        with self.store.tx():
            self._move(pid, State.APPROVED, "", handoff=int(manual))
            self.audit.append("action.approved", m["approved"], f"bound to hash {r['hash'][:12]}", pid)
            if manual:
                self.audit.append("handoff.manual", "Nothing was posted. The platform does not allow it, so you paste the reply yourself.", "no read-back possible", pid)
        if manual or not execute:
            return self._view(self._row(pid))
        return self.execute(pid)

    def _platform(self, r) -> str:
        return json.loads(r["after_json"])["platform"]

    def reject(self, pid: str, reason: str) -> dict:
        m = MSG[self._row(pid)["kind"]]
        self._move(pid, State.REJECTED, f"Reason: {reason}")
        self.audit.append("action.rejected", m["rejected"], reason, pid)
        return self._view(self._row(pid))

    # ---- execute and verify (separate from approval, and from Muse) ----
    def _precondition(self, r, before: dict, after: dict) -> str | None:
        """Re-read the world just before writing. Returns why we must not write, or None."""
        if r["kind"] == "ad":
            if self.providers["Ads"].read_ad(after["name"]) is not None:
                return "an ad with this name already exists"
            img = self.store.one("SELECT data, passed FROM images WHERE sha=?", (after["image_sha"],))
            if not img or not img["passed"] or hashlib.sha256(img["data"]).hexdigest() != after["image_sha"]:
                return "the picture is not the one that was checked"
            return None
        cur = self.providers[after["platform"]].read_review(r["review_id"])
        if cur is None or cur.reply is not None or cur.text != before["text"]:
            return "the review changed"
        return None

    def _write(self, r, after: dict) -> None:
        if r["kind"] == "ad":
            self.providers["Ads"].create_paused_draft(after["name"], after["headline"], after["text"], after["image_sha"], after["format"], r["idem"])
        else:
            self.providers[after["platform"]].post_reply(r["review_id"], after["reply"], r["idem"])

    def _readback_ok(self, r, after: dict) -> bool:
        """An independent read through the provider's read path, not the write response."""
        if r["kind"] == "ad":
            ad = self.providers["Ads"].read_ad(after["name"])
            return (ad is not None and ad.status == "paused" and ad.headline == after["headline"] and ad.text == after["text"]
                    and ad.image_sha == after["image_sha"] and ad.format == after["format"])
        back = self.providers[after["platform"]].read_review(r["review_id"])
        return back is not None and back.reply == after["reply"]

    def execute(self, pid: str) -> dict:
        r = self._row(pid)
        m = MSG[r["kind"]]
        if r["state"] != State.APPROVED.value or r["handoff"]:
            raise InvalidTransition(f"Only an approved {m['noun']} that this app can write can be executed.")
        after, before = json.loads(r["after_json"]), json.loads(r["before_json"])
        self._move(pid, State.EXECUTING)
        self.audit.append("execution.started", m["start"], r["idem"], pid)
        why = self._precondition(r, before, after)
        if why:
            self._move(pid, State.FAILED, "precondition_changed")
            self.audit.append("execution.refused", m["refused"], f"precondition_changed; {why}; nothing written", pid)
            return self._view(self._row(pid))
        try:
            self._write(r, after)
        except ManualHandoff:
            self._move(pid, State.FAILED, "manual_handoff_required")
            self.audit.append("execution.refused", "This platform does not allow posting from the app.", "manual_handoff_required", pid)
            return self._view(self._row(pid))
        except NameTaken:
            self._move(pid, State.FAILED, "precondition_changed")
            self.audit.append("execution.refused", m["refused"], "precondition_changed; an ad with this name already exists; nothing written", pid)
            return self._view(self._row(pid))
        self._move(pid, State.EXECUTED)
        self.audit.append("execution.succeeded", m["done"], m["detail_done"], pid)
        if self._readback_ok(r, after):
            self._move(pid, State.VERIFIED)
            self.audit.append("verification.passed", m["ok"], "read-back equals expected", pid)
        else:
            self._move(pid, State.FAILED, "verification_mismatch")
            self.audit.append("verification.failed", m["bad"], "read-back differs", pid)
        return self._view(self._row(pid))

    # ---- reads ----
    def get(self, pid: str) -> dict:
        return self._view(self._row(pid))

    def list_reviews(self) -> list[dict]:
        out = []
        for rv in self.providers["Google"].list_reviews():
            p = self.store.one("SELECT * FROM proposals WHERE review_id=? AND kind='reply' ORDER BY created_at DESC, attempt DESC LIMIT 1", (rv.id,))
            out.append({"review": rv.__dict__, "proposal": self._view(p) if p else None})
        return out

    def list_ads(self) -> dict:
        rows = self.store.all("SELECT * FROM proposals WHERE kind='ad' ORDER BY created_at DESC, attempt DESC")
        return {"ads": [a.__dict__ for a in self.providers["Ads"].list_ads()], "proposals": [self._view(r) for r in rows]}

    def image(self, sha: str) -> tuple[str, bytes]:
        r = self.store.one("SELECT mime, data FROM images WHERE sha=?", (sha,))
        if not r:
            raise NotFound("No such picture.")
        return r["mime"], r["data"]

    # ---- demo controls (only reachable when DEMO_CONTROLS=1) ----
    def demo_reset(self, reviews: list[dict], ads: list[dict] = ()) -> None:
        with self.store.tx():
            for t in ("proposals", "events", "writes", "reviews", "ads", "images"):
                self.store.run(f"DELETE FROM {t}")
            self.store.run("DELETE FROM sqlite_sequence WHERE name='events'")
        self.providers["Google"].seed(reviews)
        self.providers["Ads"].seed(list(ads))

    def demo_tamper(self, on: bool) -> dict:
        """Edit the text of audit entry 2 behind the app's back, to show the chain check catching it."""
        suffix = " (edited)"
        if on:
            self.store.run("UPDATE events SET plain = plain || ? WHERE seq=2 AND plain NOT LIKE ?", (suffix, "%" + suffix))
        else:
            self.store.run("UPDATE events SET plain = substr(plain, 1, length(plain) - ?) WHERE seq=2 AND plain LIKE ?", (len(suffix), "%" + suffix))
        return {"tampered": bool(self.store.one("SELECT 1 FROM events WHERE seq=2 AND plain LIKE ?", ("%" + suffix,)))}

    def usage(self) -> dict:
        r = self.store.one("SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(cached_tokens),0) c, COALESCE(SUM(output_tokens),0) o, COALESCE(SUM(cost_usd),0) usd FROM usage")
        return {"calls": r["n"], "input_tokens": r["i"], "cached_tokens": r["c"], "output_tokens": r["o"], "cost_usd": round(r["usd"], 6)}
