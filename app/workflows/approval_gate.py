"""The approval gate: the only place an ApprovedAction is made.

A person's OK is bound to the SHA-256 of the exact change they saw. This module checks that
the proposal is still waiting, has not expired, and that the hash the person saw is the stored
one. Only then does it move the proposal to APPROVED and hand back an ApprovedAction. The
executors accept nothing else, and they recompute the hash from what is stored before they
write. Nothing here writes to a provider."""
import json
from dataclasses import dataclass, field

from ..core import proposals
from ..core.domain import State
from ..core.errors import Expired, HashMismatch, InvalidTransition
from ..core.messages import MSG

_SEAL = object()


@dataclass(frozen=True)
class ApprovedAction:
    """Proof that a person approved this exact content. Build it only through this module."""
    proposal_id: str
    kind: str
    content_hash: str
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._seal is not _SEAL:
            raise TypeError("An ApprovedAction can only be made by the approval gate.")


def _authorize(rt, pid: str, seen_hash: str):
    """Checks state, expiry and the hash the person saw. Returns (row, ApprovedAction | None);
    None means a manual hand-off, where this app never writes."""
    r = proposals.row(rt.store, pid)
    m = MSG[r["kind"]]
    if r["state"] != State.PROPOSED.value:
        raise InvalidTransition(f"This {m['noun']} is {r['state'].lower()}, so it cannot be approved.")
    if rt.clock() > r["expires_at"]:
        with rt.store.tx():   # the new state and its audit entry are saved together, or not at all
            proposals.move(rt.store, pid, State.REJECTED, "expired")
            rt.audit.append("approval.expired", "Your OK came too late, so nothing was done.", "", pid)
        raise Expired("This approval request expired.")
    if seen_hash != r["hash"]:
        rt.audit.append("approval.refused", f"Your OK was for a different version of this {m['noun']}, so nothing was done.",
                        f"seen {seen_hash[:12]}, stored {r['hash'][:12]}", pid)
        raise HashMismatch(f"The {m['noun']} changed after you looked at it. Please look again.")
    manual = r["kind"] == "reply" and not rt.reader.platform_can_post(_platform(r))
    with rt.store.tx():
        proposals.move(rt.store, pid, State.APPROVED, "", handoff=int(manual))
        rt.audit.append("action.approved", m["approved"], f"bound to hash {r['hash'][:12]}", pid)
        if manual:
            rt.audit.append("handoff.manual", "Nothing was posted. The platform does not allow it, so you paste the reply yourself.", "no read-back possible", pid)
    return r, (None if manual else ApprovedAction(pid, r["kind"], r["hash"], _SEAL))


def _platform(r) -> str:
    return json.loads(r["after_json"])["platform"]


def approve(rt, pid: str, seen_hash: str, run=None) -> dict:
    """Approve the exact content the person saw. If run is given and the app is allowed to
    write, it is called with the ApprovedAction (the executor's execute) and its result is returned."""
    _, action = _authorize(rt, pid, seen_hash)
    if action is None or run is None:
        return proposals.view(proposals.row(rt.store, pid))
    return run(action)


def approved_action_for(rt, pid: str) -> ApprovedAction:
    """For a proposal that was approved earlier without running (approve with execute off).
    It stays APPROVED and the content cannot be edited after approval, so the stored hash is
    the one that was approved; the executor still recomputes it before writing."""
    r = proposals.row(rt.store, pid)
    if r["state"] != State.APPROVED.value or r["handoff"]:
        raise InvalidTransition(f"Only an approved {MSG[r['kind']]['noun']} that this app can write can be executed.")
    return ApprovedAction(pid, r["kind"], r["hash"], _SEAL)
