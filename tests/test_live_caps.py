"""Every cap, floor and the resume rule of the LIVE-LITE harness fires, proven with a stub model and a fake clock.
No Ollama, no warehouse, no network."""

import json

import anyio
import pytest

from analyticsreceipts.live import Runner, queue_from_config, read_jsonl, remaining_pairs
from analyticsreceipts.model import default_model_path, load

MODEL = load(default_model_path())
GOLDEN = {i: {"id": i, "question": f"question {i}"} for i in ("G01", "G11", "G16")}
FINAL = {"message": {"role": "assistant", "content": '{"behavior": "abstain", "resolved_spec": null}'},
         "eval_count": 10, "eval_duration": 10**9, "prompt_eval_count": 5, "prompt_eval_duration": 10**8}
TOOLCALL = {"message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "list_metrics", "arguments": {}}}]},
            "eval_count": 10, "eval_duration": 10**9, "prompt_eval_count": 5, "prompt_eval_duration": 10**8}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Exited(BaseException):
    """Stands in for os._exit; a BaseException so no `except Exception` in the harness can swallow it."""


def cfg(**kw):
    c = {"items": ["G01", "G11", "G16"], "arms": ["mcp", "raw"], "k": 1, "model": "stub", "think": True,
         "num_ctx": 8192, "max_turns": 6, "request_timeout_s": 1200, "loop_cap_s": 2700, "soft_cap_s": 21600,
         "hard_cap_s": 25200, "disk_floor_kib": 1048576, "battery_floor_pct": 10, "seed": 1}
    c.update(kw)
    return c


def make(tmp_path, clock, chat, battery=(80, "Battery Power"), free=5_000_000, **kw):
    calls = {"unload": 0, "exit": 0}

    def unload(_):
        calls["unload"] += 1

    def exit_fn(_):
        calls["exit"] += 1
        raise Exited()

    r = Runner(cfg(**kw), tmp_path / "replay.jsonl", chat=chat, clock=clock, battery=lambda: battery,
               free_kib=lambda: (free, "df"), swap=lambda: "swap", unload=unload, exit_fn=exit_fn,
               start_sampler=False)
    return r, calls


async def tool(name, args):
    return {"result_type": "ok", "receipt": None}, False


ROUTER = {"mcp": tool, "raw": tool}
TOOLS = {"mcp": [], "raw": []}


def run(r, pairs):
    return anyio.run(r.run_queue, pairs, GOLDEN, MODEL, ROUTER, TOOLS)


def test_per_loop_cap_aborts_and_records_loop_timeout(tmp_path):
    clock = Clock()
    timeouts = []

    def chat(msgs, tools, opts, timeout_s):
        timeouts.append(timeout_s)
        clock.t += 1000
        return TOOLCALL

    r, _ = make(tmp_path, clock, chat)
    reason = run(r, [("G01", "mcp")])
    recs = [x for x in read_jsonl(tmp_path / "replay.jsonl") if x["kind"] == "run"]
    assert reason == "queue_complete"
    assert len(recs) == 1 and recs[0]["loop_timeout"] is True and recs[0]["error"].startswith("loop_timeout")
    assert len(timeouts) == 3  # 0 -> 1000 -> 2000 -> 3000 s: no 4th request after the cap
    assert timeouts == [1200, 1200, 700]  # request timeout is clipped to the time left in the loop


def test_loop_under_the_cap_is_not_a_timeout(tmp_path):
    clock = Clock()

    def chat(msgs, tools, opts, timeout_s):
        clock.t += 100
        return FINAL

    r, _ = make(tmp_path, clock, chat)
    run(r, [("G01", "mcp")])
    rec = [x for x in read_jsonl(tmp_path / "replay.jsonl") if x["kind"] == "run"][0]
    assert rec["loop_timeout"] is False and rec["final_text"]


def test_soft_cap_starts_no_new_loop(tmp_path):
    clock = Clock()

    def chat(msgs, tools, opts, timeout_s):
        clock.t += 21700  # one long loop crosses 6 h
        return FINAL

    r, calls = make(tmp_path, clock, chat, loop_cap_s=10**9, request_timeout_s=10**9)
    reason = run(r, [("G01", "mcp"), ("G01", "raw"), ("G11", "mcp")])
    recs = read_jsonl(tmp_path / "replay.jsonl")
    assert reason == "soft_cap"
    assert [x["arm"] for x in recs if x["kind"] == "run"] == ["mcp"]
    stop = [x for x in recs if x.get("event") == "stop"][0]
    assert stop["reason"] == "soft_cap" and stop["not_started"] == [["G01", "raw"], ["G11", "mcp"]]
    assert calls["exit"] == 0


@pytest.mark.parametrize("name,low", [
    ("hard_cap", {"advance": 25300}),
    ("disk_floor", {"free": 500_000}),
    ("battery_floor", {"battery": (10, "Battery Power")}),
])
def test_hard_stops_mid_loop_save_inflight_unload_and_exit(tmp_path, name, low):
    """The floor is crossed DURING a request; the sampler stops the run and saves the in-flight record."""
    clock = Clock()
    state = {"battery": (80, "Battery Power"), "free": 5_000_000}
    holder = {}

    def chat(msgs, tools, opts, timeout_s):
        clock.t += low.get("advance", 50)
        state.update({k: v for k, v in low.items() if k != "advance"})
        holder["r"].sample_once()  # what the 60 s sampler thread does mid-request
        return FINAL

    calls = {"unload": 0, "exit": 0}

    def exit_fn(_):
        calls["exit"] += 1
        raise Exited()

    r = Runner(cfg(), tmp_path / "replay.jsonl", chat=chat, clock=clock, battery=lambda: state["battery"],
               free_kib=lambda: (state["free"], "df"), swap=lambda: "swap",
               unload=lambda _: calls.__setitem__("unload", calls["unload"] + 1), exit_fn=exit_fn,
               start_sampler=False)
    holder["r"] = r
    with pytest.raises(Exited):
        run(r, [("G01", "mcp"), ("G01", "raw")])
    recs = read_jsonl(tmp_path / "replay.jsonl")
    runs = [x for x in recs if x["kind"] == "run"]
    assert len(runs) == 1 and runs[0]["incomplete"] is True and runs[0]["stop_reason"] == name
    assert [x["reason"] for x in recs if x.get("event") == "stop"] == [name]
    assert calls["unload"] == 1 and calls["exit"] == 1


@pytest.mark.parametrize("name,kw", [("disk_floor", {"free": 500_000}),
                                     ("battery_floor", {"battery": (10, "Battery Power")})])
def test_floor_already_crossed_starts_no_loop(tmp_path, name, kw):
    clock = Clock()

    def chat(*a):
        raise AssertionError("no loop may start")

    r, calls = make(tmp_path, clock, chat, **kw)
    with pytest.raises(Exited):
        run(r, [("G01", "mcp")])
    recs = read_jsonl(tmp_path / "replay.jsonl")
    assert not [x for x in recs if x["kind"] == "run"]
    assert [x["reason"] for x in recs if x.get("event") == "stop"] == [name] and calls["unload"] == 1


@pytest.mark.parametrize("battery,free", [((11, "Battery Power"), 5_000_000), ((80, "Battery Power"), 1_048_576)])
def test_floors_do_not_fire_just_above_the_line(tmp_path, battery, free):
    clock = Clock()
    holder = {}

    def chat(msgs, tools, opts, timeout_s):
        clock.t += 50
        holder["r"].sample_once()
        return FINAL

    r, calls = make(tmp_path, clock, chat, battery=battery, free=free)
    holder["r"] = r
    assert run(r, [("G01", "mcp")]) == "queue_complete"
    assert calls["exit"] == 0


def test_resume_skips_completed_pairs_and_reruns_incomplete(tmp_path):
    c = cfg()
    queue = queue_from_config(c)
    prior = [{"kind": "run", "item": "G01", "arm": "mcp"}, {"kind": "run", "item": "G01", "arm": "raw"},
             {"kind": "run", "item": "G11", "arm": "mcp", "incomplete": True, "stop_reason": "battery_floor"},
             {"kind": "event", "event": "stop", "reason": "battery_floor"}]
    p = tmp_path / "replay.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in prior))
    rest = remaining_pairs(queue, read_jsonl(p))
    assert rest == [("G11", "mcp"), ("G11", "raw"), ("G16", "mcp"), ("G16", "raw")]

    clock = Clock()

    def chat(msgs, tools, opts, timeout_s):
        clock.t += 10
        return FINAL

    r, _ = make(tmp_path, clock, chat)
    assert run(r, rest) == "queue_complete"
    complete = [(x["item"], x["arm"]) for x in read_jsonl(p) if x["kind"] == "run" and not x.get("incomplete")]
    assert sorted(complete) == sorted(queue)  # every pair exactly once, appended to the same replay
    assert remaining_pairs(queue, read_jsonl(p)) == []


def test_prior_session_run_time_counts_toward_the_soft_cap(tmp_path):
    """A resumed queue continues the 6 h budget from the earlier session's run time, not from zero."""
    clock = Clock()

    def chat(msgs, tools, opts, timeout_s):
        clock.t += 700
        return FINAL

    r = Runner(cfg(), tmp_path / "replay.jsonl", chat=chat, clock=clock, battery=lambda: (80, "x"),
               free_kib=lambda: (5_000_000, "df"), swap=lambda: "s", unload=lambda _: None,
               exit_fn=lambda _: None, start_sampler=False, prior_elapsed_s=21_000)
    assert run(r, [("G11", "raw"), ("G16", "mcp")]) == "soft_cap"  # 21,000 + 700 >= 21,600 after one loop
    assert [x["arm"] for x in read_jsonl(tmp_path / "replay.jsonl") if x["kind"] == "run"] == ["raw"]


def test_without_prior_time_the_same_queue_completes(tmp_path):
    clock = Clock()

    def chat(msgs, tools, opts, timeout_s):
        clock.t += 700
        return FINAL

    r = Runner(cfg(), tmp_path / "replay.jsonl", chat=chat, clock=clock, battery=lambda: (80, "x"),
               free_kib=lambda: (5_000_000, "df"), swap=lambda: "s", unload=lambda _: None,
               exit_fn=lambda _: None, start_sampler=False)
    assert run(r, [("G11", "raw"), ("G16", "mcp")]) == "queue_complete"


def test_v1_prompt_is_unchanged_without_an_addition():
    """LIVE-LITE v1 configs carry no addition: the prompt must be byte-identical to the one v1 ran with."""
    import json as _json
    from pathlib import Path as _P

    from analyticsreceipts.live import system_prompt

    saved = _P(__file__).resolve().parents[2] / "internal" / "review" / "system-prompts-v1.json"
    if not saved.exists():
        pytest.skip("v1 prompt snapshot is internal-only")
    v1 = _json.loads(saved.read_text())
    assert system_prompt(MODEL, "mcp") == v1["mcp"] and system_prompt(MODEL, "raw") == v1["raw"]


def test_addition_is_the_only_difference():
    from analyticsreceipts.live import system_prompt

    add = "First call list_metrics to see available metrics."
    base, v2 = system_prompt(MODEL, "mcp"), system_prompt(MODEL, "mcp", add)
    assert v2.replace(" " + add, "", 1) == base and v2.count(add) == 1
