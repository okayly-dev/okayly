"""Rules that run on every reply, from Muse or from a person. Deterministic code, not a prompt:
a reply that breaks a rule cannot become a proposal, and cannot be saved after an edit."""
import re

from .domain import Issue, ReviewState

MAX_CHARS = 600

_VISIT = re.compile(
    r"\b(your|the)\s+(visit|appointment|treatment|procedure|crown|root canal|implant|filling|cleaning|"
    r"extraction|surgery|whitening|braces|invisalign|x-?rays?)\b|\bas (our|a) patient\b|\bour patient\b|"
    r"\byou (came|visited|were seen)\b|\bwhen you (came|visited)\b",
    re.I,
)
_PROMISE = re.compile(r"(guarantee|refund|free of charge|free of cost|we promise|100%|next visit will|discount)", re.I)
_HEALTH = re.compile(r"\b(pain|infection|antibiotic|medication|swelling|bleeding|you should (take|use|try|see))\b", re.I)
_PHONE = re.compile(r"\+?\(?\d{3}\)?[\s.‑-]?\d{3}[\s.‑-]?\d{4}")
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_ESCALATE = re.compile(
    r"\b(lawyer|attorney|sue|suing|lawsuit|legal action|malpractice|hipaa|billed twice|double.?billed|"
    r"overcharg\w*|fraud|insurance claim|police|report you)\b",
    re.I,
)


def needs_human(review: ReviewState) -> str | None:
    """Reviews we never draft a reply for. Returns a plain-language reason, or None."""
    hits = list(dict.fromkeys(m.group(0).lower() for m in _ESCALATE.finditer(review.text)))
    if hits:
        return "The review mentions " + ", ".join(f'"{h}"' for h in hits) + ". A person should handle this one."
    return None


def check_reply(text: str, review: ReviewState | None = None, facts: dict | None = None) -> list[Issue]:
    x = (text or "").strip()
    if not x:
        return [Issue("empty", "Write a reply first.")]
    out: list[Issue] = []
    if len(x) > MAX_CHARS:
        out.append(Issue("too_long", f"Keep it under {MAX_CHARS} characters. Yours is {len(x)}."))
    if _VISIT.search(x):
        out.append(Issue("confirms_patient", "Do not mention a visit or a treatment. That confirms the person is a patient, which can break privacy rules."))
    if _PROMISE.search(x):
        out.append(Issue("promise", "Do not promise results, refunds, discounts, free work or future service."))
    if _HEALTH.search(x):
        out.append(Issue("health_advice", "Do not give health advice."))
    if review is not None:
        first = review.who.split()[0].strip(".,").lower() if review.who else ""
        if first and len(first) > 1 and re.search(rf"\b{re.escape(first)}\b", x, re.I):
            out.append(Issue("uses_name", "Do not use the reviewer's name."))
    if facts is not None:
        allowed = {re.sub(r"\D", "", p) for p in facts.get("phones", [])}
        for m in _PHONE.finditer(x):
            if re.sub(r"\D", "", m.group(0)) not in allowed:
                out.append(Issue("unknown_phone", "That phone number is not one of your practice details."))
                break
        if _URL.search(x) and not facts.get("urls"):
            out.append(Issue("unknown_link", "Do not add links that are not in your practice details."))
    return out
