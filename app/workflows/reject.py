"""Saying "not now" to a proposal. Rejection is final; a new proposal is a new attempt."""
from ..core import proposals
from ..core.domain import State
from ..core.messages import MSG


def reject(rt, pid: str, reason: str) -> dict:
    m = MSG[proposals.row(rt.store, pid)["kind"]]
    with rt.store.tx():   # the new state and its audit entry are saved together, or not at all
        proposals.move(rt.store, pid, State.REJECTED, f"Reason: {reason}")
        rt.audit.append("action.rejected", m["rejected"], reason, pid)
    return proposals.view(proposals.row(rt.store, pid))
