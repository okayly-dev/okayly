"""Day-1 spike: what does the Muse API actually do? Standard library only, no installs.
Run: python3 -I muse_spike.py <step> ; steps: status models basic structured tools both image
The API key is read from MODEL_API_KEY and is never printed or written."""
import json, os, sys, time, urllib.request, urllib.error
BASE = "https://api.meta.ai/v1"
KEY = os.environ.get("MODEL_API_KEY", "")
MODEL = "muse-spark-1.3"
PRICE = {"in": 1.25, "cached": 0.15, "out": 4.25}  # $ per 1M tokens (API_REFERENCE, 2026-10-26)

def call(method, path, body=None, auth=True):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + KEY} if auth else {})})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}"), round(time.time() - t, 2), dict(r.headers)
    except urllib.error.HTTPError as e:
        try: payload = json.loads(e.read())
        except Exception: payload = {}
        return e.code, payload, round(time.time() - t, 2), dict(e.headers)

def cost(u):
    if not u: return None
    i = u.get("prompt_tokens", u.get("input_tokens", 0)); o = u.get("completion_tokens", u.get("output_tokens", 0))
    return round((i * PRICE["in"] + o * PRICE["out"]) / 1e6, 6)

def show(name, status, body, secs, extra=None):
    u = body.get("usage") if isinstance(body, dict) else None
    print(json.dumps({"step": name, "http": status, "seconds": secs, "usage": u, "approx_cost_usd": cost(u), **(extra or {})}, indent=1))

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["page", "new_title", "reason"],
          "properties": {"page": {"type": "string"}, "new_title": {"type": "string", "maxLength": 60}, "reason": {"type": "string"}}}
TOOL = {"type": "function", "function": {"name": "get_page_performance", "description": "Get clicks and impressions for a page path.",
        "strict": True, "parameters": {"type": "object", "additionalProperties": False, "required": ["page"], "properties": {"page": {"type": "string"}}}}}
PROMPT = "Page /services/dental-implants/ has 4,200 impressions and 38 clicks. Suggest a better page title (max 60 characters)."

def step(n):
    if n == "status":
        s, b, t, _ = call("GET", "/status", auth=False); show(n, s, b, t, {"body": b})
    elif n == "models":
        s, b, t, _ = call("GET", "/models"); ids = [m.get("id") for m in b.get("data", [])] if isinstance(b, dict) else None
        show(n, s, b, t, {"models": ids, "error": b.get("error") if s != 200 else None})
    elif n == "basic":
        s, b, t, h = call("POST", "/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": "Reply with exactly: ok"}], "max_tokens": 20})
        show(n, s, b, t, {"reply": (b.get("choices") or [{}])[0].get("message", {}).get("content"), "ratelimit_headers": {k: v for k, v in h.items() if "ratelimit" in k.lower()}, "error": b.get("error")})
    elif n == "structured":
        s, b, t, _ = call("POST", "/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "title_change", "strict": True, "schema": SCHEMA}}})
        c = (b.get("choices") or [{}])[0].get("message", {}).get("content")
        ok = False
        try: j = json.loads(c); ok = set(j) == set(SCHEMA["required"]) and len(j["new_title"]) <= 60
        except Exception: pass
        show(n, s, b, t, {"content": c, "valid_against_schema": ok, "error": b.get("error")})
    elif n == "tools":
        msgs = [{"role": "user", "content": PROMPT + " First call get_page_performance."}]
        s, b, t, _ = call("POST", "/chat/completions", {"model": MODEL, "messages": msgs, "tools": [TOOL], "tool_choice": "auto"})
        m = (b.get("choices") or [{}])[0].get("message", {}); calls = m.get("tool_calls")
        extra = {"tool_calls": calls, "error": b.get("error")}
        if calls:
            msgs += [m, {"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps({"page": "/services/dental-implants/", "impressions": 4200, "clicks": 38})}]
            s2, b2, t2, _ = call("POST", "/chat/completions", {"model": MODEL, "messages": msgs, "tools": [TOOL]})
            extra["second_http"] = s2; extra["final"] = (b2.get("choices") or [{}])[0].get("message", {}).get("content"); extra["second_usage"] = b2.get("usage"); extra["error2"] = b2.get("error")
        show(n, s, b, t, extra)
    elif n == "both":
        s, b, t, _ = call("POST", "/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": PROMPT + " Call get_page_performance first, then answer."}],
            "tools": [TOOL], "tool_choice": "auto", "response_format": {"type": "json_schema", "json_schema": {"name": "title_change", "strict": True, "schema": SCHEMA}}})
        show(n, s, b, t, {"message": (b.get("choices") or [{}])[0].get("message"), "error": b.get("error")})
    elif n == "image":
        s, b, t, _ = call("POST", "/images/generations", {"model": "muse-image-1.0", "prompt": "Flat illustration, light blue background, large text-free question mark in a rounded circle, calm dental clinic mood, no people, no faces, no text", "n": 1})
        d = (b.get("data") or [{}])[0] if isinstance(b, dict) else {}
        show(n, s, b, t, {"keys": list(d.keys()), "has_b64": bool(d.get("b64_json")), "has_url": bool(d.get("url")), "error": b.get("error")})
        if d.get("b64_json"):
            import base64; open(os.path.join(os.path.dirname(__file__), "sample-image.png"), "wb").write(base64.b64decode(d["b64_json"]))
    else:
        print("unknown step", n)


# ---- extra steps (appended after the first run) ----
def step2(n):
    if n == "search":
        s, b, t, _ = call("POST", "/responses", {"model": MODEL, "input": "In one sentence, what is the most recent Google search or Google Ads policy change you can find (give the date)?",
            "tools": [{"type": "web_search"}], "max_tool_calls": 2})
        out = b.get("output", []) if isinstance(b, dict) else []
        kinds = [o.get("type") for o in out]
        text = ""
        for o in out:
            if o.get("type") == "message":
                for c in o.get("content", []): text += c.get("text", "") or ""
        show(n, s, b, t, {"output_types": kinds, "text": text[:600], "error": b.get("error") if isinstance(b, dict) else None})
    elif n == "review":
        import base64
        img = base64.b64encode(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample-image.png"), "rb").read()).decode()
        msg = [{"role": "user", "content": [
            {"type": "text", "text": "Review this ad picture for a dental practice. Answer in JSON with keys: has_people (bool), has_before_after (bool), has_text (bool), has_health_claim (bool), notes (string)."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}}]}]
        s, b, t, _ = call("POST", "/chat/completions", {"model": MODEL, "messages": msg,
            "response_format": {"type": "json_schema", "json_schema": {"name": "review", "strict": True, "schema": {"type": "object", "additionalProperties": False,
              "required": ["has_people", "has_before_after", "has_text", "has_health_claim", "notes"],
              "properties": {"has_people": {"type": "boolean"}, "has_before_after": {"type": "boolean"}, "has_text": {"type": "boolean"}, "has_health_claim": {"type": "boolean"}, "notes": {"type": "string"}}}}}})
        show(n, s, b, t, {"content": (b.get("choices") or [{}])[0].get("message", {}).get("content") if isinstance(b, dict) else None, "error": b.get("error") if isinstance(b, dict) else None})
    else:
        step(n)
if __name__ == "__main__":
    if not KEY and sys.argv[1] != "status": sys.exit("MODEL_API_KEY is not set")
    for n in sys.argv[1:]: step2(n)
