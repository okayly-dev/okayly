from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


# Allowed moves. FAILED, REJECTED and VERIFIED are final; a new attempt is a new proposal.
# APPROVED is also final for a manual hand-off (the app cannot post to that platform).
TRANSITIONS = {
    State.PROPOSED: {State.APPROVED, State.REJECTED},
    State.APPROVED: {State.EXECUTING},
    State.EXECUTING: {State.EXECUTED, State.FAILED},
    State.EXECUTED: {State.VERIFIED, State.FAILED},
    State.VERIFIED: set(),
    State.FAILED: set(),
    State.REJECTED: set(),
}


@dataclass(frozen=True)
class ReviewState:
    id: str
    platform: str
    stars: int
    who: str
    date: str
    text: str
    reply: str | None


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


@dataclass(frozen=True)
class AdState:
    name: str
    status: str
    headline: str
    text: str
    image_sha: str | None
    format: str
