import pytest

from app.agents.loop import MAX_ROUNDS, run_tool_loop
from app.core.errors import DraftError, MuseUnavailable


class Item:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def tool_call(i=1):
    return Item(type="function_call", name="t", arguments="{}", call_id=f"c{i}")


class Script:
    """Plays a list of replies; an exception in the list is raised instead of returned."""
    def __init__(self, steps):
        self.steps, self.calls = list(steps), []

    def respond(self, **kw):
        self.calls.append(kw)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def go(muse):
    return run_tool_loop(muse, prompt="p", instructions="i", tools=[], text_format={}, run_tool=lambda n, a: {"ok": 1},
                         parse=lambda t: t, purpose="test")


def reply(output, text="done", rid="r"):
    return Item(output=output, output_text=text, id=rid)


def test_a_lost_thread_part_way_restarts_the_conversation_once():
    muse = Script([reply([tool_call()], rid="r1"), MuseUnavailable("busy"),
                   reply([tool_call()], rid="r2"), reply([], text="final", rid="r3")])
    assert go(muse) == "final"
    assert [c["previous_response_id"] for c in muse.calls] == [None, "r1", None, "r2"]


def test_a_second_lost_thread_gives_up_with_the_plain_busy_error():
    muse = Script([reply([tool_call()], rid="r1"), MuseUnavailable("busy"),
                   reply([tool_call()], rid="r2"), MuseUnavailable("busy")])
    with pytest.raises(MuseUnavailable):
        go(muse)


def test_a_failure_on_the_very_first_call_is_not_restarted():
    muse = Script([MuseUnavailable("busy")])
    with pytest.raises(MuseUnavailable):
        go(muse)
    assert len(muse.calls) == 1


def test_a_model_that_never_stops_calling_tools_ends_in_a_draft_error_not_an_endless_loop():
    muse = Script([reply([tool_call(i)], rid=f"r{i}") for i in range(MAX_ROUNDS * 2)])
    with pytest.raises(DraftError):
        go(muse)
    assert len(muse.calls) == MAX_ROUNDS
