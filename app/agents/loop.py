"""The shared Muse tool loop. Muse asks for read tools, code answers them, and the last
message must be the structured answer. The loop is capped so a confused model cannot spin."""
import json

from ..core.errors import DraftError, MuseUnavailable
from ..core.messages import MUSE_BAD_OUTPUT

MAX_ROUNDS = 5
RESTARTS = 1   # if Muse loses the conversation thread part-way, start it again from the beginning once


def load_args(raw: str | None) -> dict | None:
    """Tool arguments from the model are untrusted: a JSON object, or None."""
    try:
        args = json.loads(raw or "{}")
    except ValueError:
        return None
    return args if isinstance(args, dict) else None


def run_tool_loop(muse, *, prompt: str, instructions: str, tools: list, text_format: dict, run_tool, parse, purpose: str,
                  max_rounds: int = MAX_ROUNDS):
    for restart in range(RESTARTS + 1):
        inp, prev = [{"role": "user", "content": prompt}], None
        try:
            for _ in range(max_rounds):
                r = muse.respond(input=inp, instructions=instructions, tools=tools, text_format=text_format,
                                 previous_response_id=prev, purpose=purpose)
                calls = [o for o in r.output if o.type == "function_call"]
                if not calls:
                    return parse(r.output_text)
                inp = [{"type": "function_call_output", "call_id": c.call_id,
                        "output": json.dumps(run_tool(c.name, c.arguments))} for c in calls]
                prev = r.id
        except MuseUnavailable:
            if prev is None or restart == RESTARTS:
                raise
            continue   # the thread was lost mid-conversation: begin again
        raise DraftError(MUSE_BAD_OUTPUT)
