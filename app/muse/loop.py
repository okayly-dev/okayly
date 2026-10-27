"""The shared Muse tool loop. Muse asks for read tools, code answers them, and the last
message must be the structured answer. The loop is capped so a confused model cannot spin."""
import json

MAX_ROUNDS = 5


class DraftError(Exception):
    pass


def load_args(raw: str | None) -> dict | None:
    """Tool arguments from the model are untrusted: a JSON object, or None."""
    try:
        args = json.loads(raw or "{}")
    except ValueError:
        return None
    return args if isinstance(args, dict) else None


def run_tool_loop(muse, *, prompt: str, instructions: str, tools: list, text_format: dict, run_tool, parse, purpose: str,
                  max_rounds: int = MAX_ROUNDS):
    inp, prev = [{"role": "user", "content": prompt}], None
    for _ in range(max_rounds):
        r = muse.respond(input=inp, instructions=instructions, tools=tools, text_format=text_format,
                         previous_response_id=prev, purpose=purpose)
        calls = [o for o in r.output if o.type == "function_call"]
        if not calls:
            return parse(r.output_text)
        inp = [{"type": "function_call_output", "call_id": c.call_id,
                "output": json.dumps(run_tool(c.name, c.arguments))} for c in calls]
        prev = r.id
    raise DraftError("Muse kept calling tools and did not finish")
