import json

import pytest

from app.agents.loop import MAX_ROUNDS, REFUSED_NAME, run_tool_loop
from app.core.errors import DraftError, MuseUnavailable


class Item:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def tool_call(i=1, name="t"):
    return Item(type="function_call", name=name, arguments="{}", call_id=f"c{i}")


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


def test_the_loop_notes_each_tool_call_with_the_size_of_its_answer():
    muse = Script([reply([tool_call(1)], rid="r1"), reply([tool_call(2)], rid="r2"), reply([], text="final", rid="r3")])
    log = []
    run_tool_loop(muse, prompt="p", instructions="i", tools=[{"name": "t"}], text_format={}, run_tool=lambda n, a: {"ok": "abc"},
                  parse=lambda t: t, purpose="test", tool_log=log)
    assert log == [{"tool": "t", "chars": len('{"ok": "abc"}'), "error": False, "refused": False}] * 2


def test_a_restarted_conversation_does_not_double_count_tool_calls():
    muse = Script([reply([tool_call()], rid="r1"), MuseUnavailable("busy"),
                   reply([tool_call()], rid="r2"), reply([], text="final", rid="r3")])
    log = []
    run_tool_loop(muse, prompt="p", instructions="i", tools=[{"name": "t"}], text_format={}, run_tool=lambda n, a: {"error": "no"},
                  parse=lambda t: t, purpose="test", tool_log=log)
    assert len(log) == 1 and log[0]["error"] is True


def test_a_tool_name_that_was_not_offered_is_never_copied_into_the_log():
    """Muse chooses the name it sends, so a hostile review could make it spell out customer words."""
    hostile = "Jane Doe had a root canal on Tuesday <script>alert(1)</script>\nsecond line " + "x" * 200
    muse = Script([reply([tool_call(1, name=hostile)], rid="r1"), reply([tool_call(2, name="t ")], rid="r2"),
                   reply([tool_call(3, name="t")], rid="r3"), reply([], text="final", rid="r4")])
    log = []
    run_tool_loop(muse, prompt="p", instructions="i", tools=[{"name": "t"}], text_format={},
                  run_tool=lambda n, a: {"error": "unknown tool " + n}, parse=lambda t: t, purpose="test", tool_log=log)
    assert [entry["refused"] for entry in log] == [True, True, False]
    assert log[2]["tool"] == "t"
    assert log[0]["tool"] == log[1]["tool"] == REFUSED_NAME
    assert "Jane" not in json.dumps(log) and "script" not in json.dumps(log)
