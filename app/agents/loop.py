"""The shared Muse tool loop. Muse asks for read tools, code answers them, and the last
message must be the structured answer. The loop is capped so a confused model cannot spin."""
import json

from ..core.errors import DraftError, MuseUnavailable
from ..core.messages import MUSE_BAD_OUTPUT

MAX_ROUNDS = 5
REFUSED_NAME = "(a tool we did not offer)"   # shown in the log instead of a name Muse made up
RESTARTS = 1   # if Muse loses the conversation thread part-way, start it again from the beginning once


def load_args(raw: str | None) -> dict | None:
    """Tool arguments from the model are untrusted: a JSON object, or None."""
    try:
        args = json.loads(raw or "{}")
    except ValueError:
        return None
    return args if isinstance(args, dict) else None


def answer_tool_calls(calls, run_tool, tool_log, offered_names=frozenset()) -> list:
    """Run each tool Muse asked for. The log keeps the size of each answer, never the answer. Muse picks the name it
    sends, so the log shows a name only if we offered that tool; any other name could carry customer words."""
    outputs = []
    for call in calls:
        answer = run_tool(call.name, call.arguments)
        text = json.dumps(answer)
        if tool_log is not None:
            offered = str(call.name) in offered_names
            tool_log.append({"tool": str(call.name) if offered else REFUSED_NAME, "chars": len(text),
                             "error": "error" in answer, "refused": not offered})
        outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": text})
    return outputs


def run_tool_loop(muse, *, prompt: str, instructions: str, tools: list, text_format: dict, run_tool, parse, purpose: str,
                  max_rounds: int = MAX_ROUNDS, tool_log: list | None = None):
    offered_names = {tool["name"] for tool in tools}
    for restart in range(RESTARTS + 1):
        if tool_log is not None:
            tool_log.clear()   # a restarted conversation starts its record again
        inp, prev = [{"role": "user", "content": prompt}], None
        try:
            for _ in range(max_rounds):
                r = muse.respond(input=inp, instructions=instructions, tools=tools, text_format=text_format,
                                 previous_response_id=prev, purpose=purpose)
                calls = [o for o in r.output if o.type == "function_call"]
                if not calls:
                    return parse(r.output_text)
                inp = answer_tool_calls(calls, run_tool, tool_log, offered_names)
                prev = r.id
        except MuseUnavailable:
            if prev is None or restart == RESTARTS:
                raise
            continue   # the thread was lost mid-conversation: begin again
        raise DraftError(MUSE_BAD_OUTPUT)
