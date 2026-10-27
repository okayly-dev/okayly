"""The exact content of a change, and its hash. An approval is bound to this hash, and the
executor recomputes it from what is stored before it writes anything."""
from .canonical import hash_of


def change_payload(kind: str, provider: str, resource: str, before: dict, after: dict, attempt: int) -> dict:
    if kind == "ad":
        return {"env": "sandbox", "provider": provider, "kind": "ad", "resource": resource,
                "operation": "create_paused_ad_draft", "before": before, "after": after, "attempt": attempt,
                "currency": "USD", "spend_usd": 0}
    return {"env": "sandbox", "provider": provider, "kind": "reply", "resource": resource,
            "operation": "post_review_reply", "before": before, "after": after, "attempt": attempt}


def content_hash(kind: str, provider: str, resource: str, before: dict, after: dict, attempt: int) -> str:
    return hash_of(change_payload(kind, provider, resource, before, after, attempt))
