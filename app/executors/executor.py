"""The executor: the only code that holds a provider write handle.

It takes an ApprovedAction (made only by the approval gate) and, before writing anything:
1. recomputes the SHA-256 of the stored content and refuses if it differs from the approved
   hash or the stored hash (approved_content_changed);
2. re-reads the world and refuses if it changed (precondition_changed).
After writing it reads back through the independent read path and compares. The comparisons
themselves are pure functions in verification.readback."""
import json

from ..core import proposals
from ..core.audit import Audit
from ..core.domain import State
from ..core.errors import InvalidTransition
from ..core.messages import MSG
from ..providers.sandbox import ManualHandoff, NameTaken
from ..verification import readback
from ..workflows.approval_gate import ApprovedAction


class Executor:
    def __init__(self, store, audit: Audit, writers: dict, reader):
        """writers: platform -> write-side provider. reader: the independent read path."""
        self.store, self.audit, self._writers, self.reader = store, audit, writers, reader

    def _current(self, kind: str, after: dict, review_id: str):
        return self.reader.read_ad(after["name"]) if kind == "ad" else self.reader.read_review(review_id)

    def _write(self, r, after: dict) -> None:
        if r["kind"] == "ad":
            self._writers["Ads"].create_paused_draft(after["name"], after["headline"], after["text"], after["image_sha"], after["format"], r["idem"])
        else:
            self._writers[after["platform"]].post_reply(r["review_id"], after["reply"], r["idem"])

    def execute(self, approved: ApprovedAction) -> dict:
        if not isinstance(approved, ApprovedAction):
            raise TypeError("The executor only accepts an ApprovedAction from the approval gate.")
        pid = approved.proposal_id
        r = proposals.row(self.store, pid)
        m = MSG[r["kind"]]
        if r["state"] != State.APPROVED.value or r["handoff"] or r["kind"] != approved.kind:
            raise InvalidTransition(f"Only an approved {m['noun']} that this app can write can be executed.")
        after, before = json.loads(r["after_json"]), json.loads(r["before_json"])
        with self.store.tx():
            proposals.move(self.store, pid, State.EXECUTING)
            changed = readback.approved_content_problem(
                kind=r["kind"], provider=r["provider"], resource=r["review_id"], before=before, after=after,
                attempt=r["attempt"], approved_hash=approved.content_hash, stored_hash=r["hash"])
            if changed:
                proposals.move(self.store, pid, State.FAILED, "approved_content_changed")
                self.audit.append("execution.refused", m["tampered"], f"approved_content_changed; {changed}; nothing written", pid)
                return proposals.view(proposals.row(self.store, pid))
            self.audit.append("execution.started", m["start"], r["idem"], pid)
        image = None
        if r["kind"] == "ad":
            image = self.store.one("SELECT data, passed FROM images WHERE sha=?", (after["image_sha"],))
        why = readback.precondition_problem(r["kind"], before, after, self._current(r["kind"], after, r["review_id"]), image)
        if why:
            proposals.move(self.store, pid, State.FAILED, "precondition_changed")
            self.audit.append("execution.refused", m["refused"], f"precondition_changed; {why}; nothing written", pid)
            return proposals.view(proposals.row(self.store, pid))
        try:
            self._write(r, after)
        except ManualHandoff:
            proposals.move(self.store, pid, State.FAILED, "manual_handoff_required")
            self.audit.append("execution.refused", "This platform does not allow posting from the app.", "manual_handoff_required", pid)
            return proposals.view(proposals.row(self.store, pid))
        except NameTaken:
            proposals.move(self.store, pid, State.FAILED, "precondition_changed")
            self.audit.append("execution.refused", m["refused"], "precondition_changed; an ad with this name already exists; nothing written", pid)
            return proposals.view(proposals.row(self.store, pid))
        proposals.move(self.store, pid, State.EXECUTED)
        self.audit.append("execution.succeeded", m["done"], m["detail_done"], pid)
        if readback.readback_matches(r["kind"], after, self._current(r["kind"], after, r["review_id"])):
            proposals.move(self.store, pid, State.VERIFIED)
            self.audit.append("verification.passed", m["ok"], "read-back equals expected", pid)
        else:
            proposals.move(self.store, pid, State.FAILED, "verification_mismatch")
            self.audit.append("verification.failed", m["bad"], "read-back differs", pid)
        return proposals.view(proposals.row(self.store, pid))
