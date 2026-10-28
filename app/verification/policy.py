"""Rules that run on every reply, from Muse or from a person. Deterministic code, not a prompt:
a reply that breaks a rule cannot become a proposal, and cannot be saved after an edit."""
import re
import unicodedata

from ..core.domain import Issue, ReviewState

MAX_CHARS = 600

_VISIT = re.compile(
    r"\b(your|the)\s+(visit|appointment|treatment|procedure|crown|root canal|implant|filling|cleaning|"
    r"extraction|surgery|whitening|braces|invisalign|x-?rays?)\b|\bas (our|a) patient\b|\bour patient\b|"
    r"\byour\s+next(?:\s+\w+)?\s+(visit|appointment|treatment|procedure|crown|root canal|implant|filling|cleaning|"
    r"extraction|surgery|whitening|braces|invisalign|x-?rays?)\b|\bas one of our patients\b|"
    r"\byou (came|visited|were seen)\b|\bwhen you (came|visited)\b",
    re.I,
)
_PROMISE = re.compile(
    r"(guarantee|refund|free of charge|free of cost|we promise|100%|next visit will|discount|"
    r"\bfree\s+(?:implant|filling|cleaning|extraction|whitening|braces|invisalign|x-?rays?|"
    r"crown|root canal|treatment|procedure|surgery)\b)",
    re.I,
)
_HEALTH = re.compile(r"\b(pain|infection|antibiotic|medication|swelling|bleeding|you should (take|use|try|see))\b", re.I)
_PHONE = re.compile(r"\+?\(?\d{3}\)?[\s.‑-]?\d{3}[\s.‑-]?\d{4}")
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_ESCALATE = re.compile(
    r"\b(lawyer|attorney|sue|suing|lawsuit|legal action|malpractice|hipaa|billed twice|double.?billed|"
    r"overcharg\w*|fraud|insurance claim|police|report you)\b",
    re.I,
)

_LINK_CONFUSABLES = str.maketrans({
    "а": "a", "с": "c", "е": "e", "і": "i", "о": "o", "р": "p", "ѕ": "s", "т": "t", "х": "x",
})


def _normalize_for_link_check(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(_LINK_CONFUSABLES)
    return re.sub(r"\s*\.\s*", ".", normalized)


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
        if _URL.search(_normalize_for_link_check(x)) and not facts.get("urls"):
            out.append(Issue("unknown_link", "Do not add links that are not in your practice details."))
    return out


# ---------- ads ----------
AD_HEADLINE_MAX = 40
AD_TEXT_MAX = 125
AD_FORMATS = ("wide", "square", "tall")
MAX_IMAGE_BYTES = 8_000_000

AD_RULES_TEXT = (
    "Headline up to 40 characters, text up to 125. No before-and-after, no results or guarantees, no health claims, "
    "no ratings or awards, no talk of patients or reviews, no prices or free offers unless the practice details list them. "
    "Pictures: no people, no before-and-after, no health claims, any text large enough to read on a phone."
)

_BEFORE_AFTER = re.compile(
    r"before\s*(?:[-–—]\s*(?:and|&|/)\s*[-–—]|(?:and|&|/)|[-–—])\s*after|"
    r"\btransformation\b|\bmakeover\b",
    re.I,
)
_RESULTS = re.compile(
    r"(guarantee\w*|painless|pain-?free|\bcures?\b|\bcured\b|risk-?free|perfect smile|results? (in|within)|"
    r"best (dentist|dental)|#\s?1|number one|top-?rated|award|"
    r"\b(?:one|two|three|four|five)[-\s]+stars?\b|\b\d(\.\d)?\s*(stars?|★)|\brated\b)", re.I)
_PRICE = re.compile(r"(\$\s?\d|\d+\s?%\s?off|\bfree\b|discount|\bsale\b|\bcoupon\b)", re.I)
_PROOF = re.compile(r"(our patients|patients (say|love|trust|agree)|testimonial|reviews? (say|show)|thousands of)", re.I)
_PERSONAL_HEALTH = re.compile(r"\b(your (pain|infection|gum disease|cavit\w+|decay)|fix your|heal\w*)\b", re.I)


def check_ad(headline: str, text: str, facts: dict | None = None) -> list[Issue]:
    h, t = (headline or "").strip(), (text or "").strip()
    if not h or not t:
        return [Issue("empty", "An ad needs a headline and some text.")]
    out: list[Issue] = []
    if len(h) > AD_HEADLINE_MAX:
        out.append(Issue("headline_too_long", f"Keep the headline under {AD_HEADLINE_MAX} characters. Yours is {len(h)}."))
    if len(t) > AD_TEXT_MAX:
        out.append(Issue("text_too_long", f"Keep the text under {AD_TEXT_MAX} characters. Yours is {len(t)}."))
    both = f"{h}\n{t}"
    if _BEFORE_AFTER.search(both):
        out.append(Issue("before_after", "Do not use before-and-after or transformation wording."))
    if _RESULTS.search(both):
        out.append(Issue("results_claim", "Do not promise results or use ratings, awards or \"best\" claims."))
    if _PERSONAL_HEALTH.search(both) or _HEALTH.search(both):
        out.append(Issue("health_claim", "Do not make health claims or speak to a person's health problem."))
    if _PROOF.search(both):
        out.append(Issue("patient_proof", "Do not talk about patients, reviews or testimonials in an ad."))
    offers = [o.lower() for o in (facts or {}).get("offers", [])]
    if _PRICE.search(both) and not any(o in both.lower() for o in offers):
        out.append(Issue("price_claim", "Do not mention prices, discounts or free offers. They are not in your practice details."))
    if facts is not None:
        allowed = {re.sub(r"\D", "", p) for p in facts.get("phones", [])}
        if any(re.sub(r"\D", "", m.group(0)) not in allowed for m in _PHONE.finditer(both)):
            out.append(Issue("unknown_phone", "That phone number is not one of your practice details."))
        if _URL.search(both) and not facts.get("urls"):
            out.append(Issue("unknown_link", "Do not add links that are not in your practice details."))
    return out


def sniff_image(data: bytes) -> str | None:
    """The real type from the first bytes, not from a name or a header the sender controls."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


_IMAGE_FAIL = {
    "no_people": "The picture shows people. We do not use people in ads.",
    "no_before_after": "The picture looks like a before-and-after.",
    "no_health_claim": "The picture makes a health claim.",
    "text_legible": "Text in the picture is hard to read on a phone.",
}


def check_image(data: bytes, review: dict | None) -> list[Issue]:
    """The code decides, not the model: every check Spark reported must be exactly True."""
    out: list[Issue] = []
    if sniff_image(data) is None:
        return [Issue("not_an_image", "That is not a picture we can use.")]
    if len(data) > MAX_IMAGE_BYTES:
        out.append(Issue("image_too_big", "The picture file is too large."))
    if not isinstance(review, dict):
        return out + [Issue("not_reviewed", "This picture was not checked.")]
    for key, msg in _IMAGE_FAIL.items():
        if review.get(key) is not True:
            out.append(Issue(key, msg))
    return out
