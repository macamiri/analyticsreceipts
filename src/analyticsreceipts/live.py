"""LIVE-LITE harness: a local model (Ollama) answers golden questions in two arms, as a fixed-priority
queue under hard time caps. Whatever completes is the result; the order is fixed before the run.

  mcp  the semantic-layer MCP server's tools (no raw SQL)
  raw  the harness's describe_tables + run_sql
Both arms get the same system prompt: the same business conventions text (the model's ai_context) and
the same output contract. Only the tools differ. The model sees compact tool results; the harness keeps
every full receipt. Thinking is recorded as a size only and is not fed back.

Caps and floors (each one has a test in tests/test_live_caps.py, with a stub model):
  * per-loop cap: a loop that runs past `loop_cap_s` is aborted and recorded as a loop-timeout;
  * global soft cap: no new loop starts once `soft_cap_s` has elapsed;
  * global hard cap: at `hard_cap_s` the in-flight record is saved (incomplete) and the process stops;
  * disk floor: below 1 GiB free, the same clean stop;
  * battery floor: at or below `battery_floor_pct`, the same clean stop, then the model is unloaded.
Every run record is appended to the JSONL replay as soon as it ends (flush + fsync). A record saved by
a stop is marked incomplete. A resumed run (--resume) continues from the first (item, arm) that has no
complete record, appending to the same replay; incomplete records are re-run.

Usage:
  python -m analyticsreceipts.live --config live-lite-config.json --db retail.duckdb --out replay.jsonl [--resume]
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import anyio

from .contract import CONTRACT_TEXT
from .model import default_model_path, load
from .paths import find_root
from .rawtools import TOOL_SPECS, compact

ROOT = find_root() or Path.cwd()  # eval data: see paths.py (a clone's root, or $ANALYTICSRECEIPTS_ROOT)
OLLAMA = "http://127.0.0.1:11434/api/chat"


# ---------------------------------------------------------------- prompts and IO
def system_prompt(model, arm, addition=None):
    """The system prompt for one arm. `addition` (from the run config, per arm) is inserted right after the
    tool sentence; without it the prompt is exactly the LIVE-LITE v1 prompt."""
    tools = ("Use the tools list_metrics, get_metric, list_dimensions, get_dimension_values and query_metric."
             if arm == "mcp" else
             "Use the tools describe_tables and run_sql (DuckDB SQL over the table raw_lines).")
    if addition:
        tools = tools + " " + addition
    return ("You answer business questions about a UK online retailer's sales data. " + tools + "\n\n"
            "Business conventions:\n" + model.instructions + "\n\n" + CONTRACT_TEXT)


def append_jsonl(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def ollama_chat(messages, tools, opts, timeout_s):
    body = {"model": opts["model"], "messages": messages, "stream": False, "think": opts["think"],
            "tools": tools, "options": {"num_ctx": opts["num_ctx"], "seed": opts["seed"]}}
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return json.load(r)


def read_battery():
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)%", out)
    src = re.search(r"'([^']+)'", out)
    return (int(m.group(1)) if m else None), (src.group(1) if src else None)


def read_free_kib():
    df = subprocess.run(["df", "-k", os.path.expanduser("~")], capture_output=True, text=True).stdout.strip().splitlines()[-1]
    return int(df.split()[3]), df


def read_swap():
    return subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout.strip()


def read_lowpowermode():
    out = subprocess.run(["pmset", "-g"], capture_output=True, text=True).stdout
    m = re.search(r"lowpowermode\s+(\d)", out)
    return int(m.group(1)) if m else None


def ollama_unload(model):
    exe = Path.home() / ".local/ollama-0.40.0/ollama"
    cmd = [str(exe) if exe.exists() else "ollama", "stop", model]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def conditions():
    pct, src = read_battery()
    free, _ = read_free_kib()
    return {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "power_source": src, "battery_pct": pct,
            "lowpowermode": read_lowpowermode(), "free_kib": free, "swapusage": read_swap()}


# ---------------------------------------------------------------- queue
def queue_from_config(cfg):
    return [(item, arm) for item in cfg["items"] for arm in cfg["arms"] for _ in range(cfg.get("k", 1))]


def remaining_pairs(queue, replay_records):
    """The fixed queue minus pairs that already have a COMPLETE record (incomplete ones are re-run)."""
    done = {}
    for r in replay_records:
        if r.get("kind") == "run" and not r.get("incomplete"):
            key = (r["item"], r["arm"])
            done[key] = done.get(key, 0) + 1
    out = []
    for pair in queue:
        if done.get(pair, 0) > 0:
            done[pair] -= 1
        else:
            out.append(pair)
    return out


class Stop(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- runner
class Runner:
    """All side effects are injectable so the caps can be tested with a stub model and a fake clock."""

    def __init__(self, cfg, out_path, *, chat=ollama_chat, clock=time.monotonic, battery=read_battery,
                 free_kib=read_free_kib, swap=read_swap, unload=ollama_unload, exit_fn=os._exit,
                 sample_every_s=60.0, start_sampler=True, prior_elapsed_s=0.0):
        self.cfg, self.out = cfg, str(out_path)
        self.chat, self.clock, self.battery, self.free_kib, self.swap = chat, clock, battery, free_kib, swap
        self.unload, self.exit_fn = unload, exit_fn
        self.t0 = clock()
        self.prior_elapsed_s = float(prior_elapsed_s)  # run time of earlier sessions of the same queue
        self.lock = threading.Lock()
        self.inflight = None  # the record of the loop in progress
        self.stopped = None
        self.sample_every_s = sample_every_s
        self._stop_evt = threading.Event()
        if start_sampler:
            threading.Thread(target=self._sampler, daemon=True).start()

    # --- guards ---------------------------------------------------------------
    def elapsed(self):
        """Run time across sessions: earlier sessions' run time plus this session's (a break is not counted)."""
        return self.prior_elapsed_s + self.clock() - self.t0

    def guard_reason(self):
        """Reason to stop NOW (hard), or None. Checked by the sampler and between steps."""
        if self.elapsed() >= self.cfg["hard_cap_s"]:
            return "hard_cap"
        free, _ = self.free_kib()
        if free < self.cfg["disk_floor_kib"]:
            return "disk_floor"
        pct, _ = self.battery()
        if pct is not None and pct <= self.cfg["battery_floor_pct"]:
            return "battery_floor"
        return None

    def hard_stop(self, reason):
        """Save the in-flight record as incomplete, unload the model, record the stop, exit."""
        with self.lock:
            if self.stopped:
                return
            self.stopped = reason
            if self.inflight is not None and not self.inflight.get("_saved"):
                rec = {k: v for k, v in self.inflight.items() if not k.startswith("_")}
                rec.update(incomplete=True, stop_reason=reason, seconds=round(self.clock() - self.inflight["_t0"], 2))
                append_jsonl(self.out, rec)
                self.inflight["_saved"] = True
            try:
                self.unload(self.cfg["model"])
            finally:
                append_jsonl(self.out, {"kind": "event", "event": "stop", "reason": reason,
                                        "elapsed_s": round(self.elapsed(), 1), "conditions": self._cond()})
        self.exit_fn(3)

    def _cond(self):
        pct, src = self.battery()
        free, _ = self.free_kib()
        return {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "battery_pct": pct, "power_source": src,
                "free_kib": free, "swapusage": self.swap()}

    def sample_once(self):
        append_jsonl(self.out + ".resources.log", self._cond())
        reason = self.guard_reason()
        if reason:
            self.hard_stop(reason)
        return reason

    def _sampler(self):
        while not self._stop_evt.is_set():
            self.sample_once()
            self._stop_evt.wait(self.sample_every_s)

    # --- one loop --------------------------------------------------------------
    async def one_run(self, arm, item, call_tool, tools, semantic_model, seed):
        cfg = self.cfg
        addition = (cfg.get("system_prompt_addition") or {}).get(arm)
        msgs = [{"role": "system", "content": system_prompt(semantic_model, arm, addition)},
                {"role": "user", "content": item["question"]}]
        t0 = self.clock()
        rec = {"kind": "run", "label": "LIVE-LITE", "arm": arm, "item": item["id"], "seed": seed,
               "model": cfg["model"], "think": cfg["think"], "num_ctx": cfg["num_ctx"], "turns": [],
               "tool_calls": [], "receipts": [], "final_text": None, "error": None, "loop_timeout": False,
               "_t0": t0}
        with self.lock:
            self.inflight = rec
        try:
            for _ in range(cfg["max_turns"]):
                remaining = cfg["loop_cap_s"] - (self.clock() - t0)
                if remaining <= 0:
                    rec["loop_timeout"] = True
                    break
                try:
                    resp = self.chat(msgs, tools, dict(cfg, seed=seed), min(cfg["request_timeout_s"], remaining))
                except Exception as e:  # a request timeout inside the loop cap is a loop-timeout too
                    if self.clock() - t0 >= cfg["loop_cap_s"] - 1:
                        rec["loop_timeout"] = True
                    rec["error"] = f"{type(e).__name__}: {e}"
                    break
                m = resp["message"]
                rec["turns"].append({k: resp.get(k) for k in ("prompt_eval_count", "prompt_eval_duration",
                                                              "eval_count", "eval_duration", "total_duration")}
                                    | {"n_tool_calls": len(m.get("tool_calls") or []),
                                       "thinking_chars": len(m.get("thinking") or ""),
                                       "content_chars": len(m.get("content") or "")})
                msgs.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls")})
                if not m.get("tool_calls"):
                    rec["final_text"] = m.get("content", "")
                    break
                for tc in m["tool_calls"]:
                    name, args = tc["function"]["name"], tc["function"].get("arguments") or {}
                    body, is_error = await call_tool(name, args)
                    rc = body.get("receipt") if isinstance(body, dict) else None
                    if rc:
                        rec["receipts"].append(rc)
                    rec["tool_calls"].append({"name": name, "arguments": args, "tool_error": is_error,
                                              "result_type": body.get("result_type") if isinstance(body, dict) else None})
                    msgs.append({"role": "tool", "tool_name": name,
                                 "content": compact(body) if isinstance(body, dict) else str(body)})
                if self.clock() - t0 >= cfg["loop_cap_s"]:
                    rec["loop_timeout"] = True
                    break
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["seconds"] = round(self.clock() - t0, 2)
        if rec["loop_timeout"] and not rec["error"]:
            rec["error"] = f"loop_timeout: exceeded {cfg['loop_cap_s']} s"
        with self.lock:
            if not rec.get("_saved"):
                append_jsonl(self.out, {k: v for k, v in rec.items() if not k.startswith("_")})
                rec["_saved"] = True
            self.inflight = None
        return rec

    # --- the queue -------------------------------------------------------------
    async def run_queue(self, pairs, golden, semantic_model, tool_router, tool_lists):
        """Runs pairs in order. Returns the stop reason (soft cap or queue complete); hard stops exit."""
        for idx, (item_id, arm) in enumerate(pairs):
            if self.elapsed() >= self.cfg["soft_cap_s"]:
                append_jsonl(self.out, {"kind": "event", "event": "stop", "reason": "soft_cap",
                                        "elapsed_s": round(self.elapsed(), 1), "not_started": [list(p) for p in pairs[idx:]]})
                return "soft_cap"
            reason = self.guard_reason()
            if reason:
                self.hard_stop(reason)
                return reason
            rec = await self.one_run(arm, golden[item_id], tool_router[arm], tool_lists[arm], semantic_model,
                                     self.cfg["seed"])
            print(item_id, arm, rec["seconds"], (rec["error"] or "")[:60], flush=True)
        append_jsonl(self.out, {"kind": "event", "event": "stop", "reason": "queue_complete",
                                "elapsed_s": round(self.elapsed(), 1)})
        return "queue_complete"

    def close(self):
        self._stop_evt.set()


# ---------------------------------------------------------------- live wiring
async def run_live(cfg, db, out, resume, prior_elapsed_s=0.0, prior_elapsed_note=None):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from .execution import Executor
    from .rawtools import RawTools

    model = load(default_model_path())
    golden = {i["id"]: i for i in json.loads((ROOT / "golden" / "golden-v1.json").read_text())["items"]}
    queue = queue_from_config(cfg)
    prior = read_jsonl(out)
    pairs = remaining_pairs(queue, prior) if resume else queue
    runner = Runner(cfg, out, prior_elapsed_s=prior_elapsed_s)
    append_jsonl(out, {"kind": "event", "event": "start", "resume": resume, "config_sha256": cfg["_sha256"],
                       "prior_elapsed_s": prior_elapsed_s, "prior_elapsed_note": prior_elapsed_note,
                       "pairs_remaining": [list(p) for p in pairs], "conditions": conditions(),
                       "semantic_model_sha256": model.sha256})
    raw = RawTools(Executor(db))
    raw_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                   "parameters": t["input_schema"]}} for t in TOOL_SPECS]
    p = StdioServerParameters(command=sys.executable, args=["-I", "-m", "analyticsreceipts.server"],
                              env={"ANALYTICSRECEIPTS_DB": str(Path(db).resolve())})
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tl = await s.list_tools()
            mcp_tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                           "parameters": t.input_schema}} for t in tl.tools]

            async def call_mcp(name, args):
                res = await s.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                if res.is_error:
                    return {"result_type": "tool_error", "error": text[:500]}, True
                try:
                    return json.loads(text), False
                except json.JSONDecodeError:
                    return {"result_type": "ok", "text": text[:2000]}, False

            async def call_raw(name, args):
                return raw.call(name, args), False

            reason = await runner.run_queue(pairs, golden, model, {"mcp": call_mcp, "raw": call_raw},
                                            {"mcp": mcp_tools, "raw": raw_tools})
    runner.close()
    ollama_unload(cfg["model"])
    append_jsonl(out, {"kind": "event", "event": "end", "reason": reason, "conditions": conditions()})
    return reason


def load_config(path):
    raw = Path(path).read_bytes()
    cfg = json.loads(raw)
    cfg["_sha256"] = hashlib.sha256(raw).hexdigest()
    return cfg


def live_report(path, label=None):
    from .report import axis_table, cell_table, grade_runs, wilson

    recs = read_jsonl(path)
    runs = [r for r in recs if r.get("kind", "run") == "run" and not r.get("incomplete")]
    incomplete = [r for r in recs if r.get("kind") == "run" and r.get("incomplete")]
    events = [r for r in recs if r.get("kind") == "event"]
    for r in runs:
        r["id"] = f"{r['item']}/{r['arm']}"
    grades = grade_runs(runs)
    lines = ["# M1 LIVE-LITE report", ""] + ([f"**{label}**", ""] if label else []) + [
             "**Label: LIVE-LITE.** One local model, one run per (item, arm), a fixed-priority queue under hard "
             "time caps: whatever completed is the result. N is tiny: every number is a count, intervals are "
             "Wilson 95 %, and no comparison between arms is claimed.", ""]
    lines += ["## Events", ""] + [f"- {e['event']}: " + json.dumps({k: v for k, v in e.items() if k not in ('kind', 'event')}, default=str) for e in events] + [""]
    lines += ["## Per-axis results", "", axis_table(grades), "", "## Cells", "", cell_table(grades), ""]
    for arm in sorted({g["arm"] for g in grades}):
        gs = [g for g in grades if g["arm"] == arm]
        k = sum(g["cell"] == "valid_wrong_question" for g in gs)
        lines.append(f"- {arm}: valid SQL, wrong question = {k}/{len(gs)}, Wilson 95 % {wilson(k, len(gs))}")
    lines += ["", "## Per run", "",
              "| item | arm | s | turns | tool calls (failed) | loop-timeout | tok/s | a | b | c | d | cell | trap | receipts |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    gmap = {g["run_id"]: g for g in grades}
    for r in runs:
        g = gmap[r["id"]]
        ev = sum((t.get("eval_count") or 0) for t in r["turns"])
        ed = sum((t.get("eval_duration") or 0) for t in r["turns"]) / 1e9
        fails = sum(1 for c in r["tool_calls"] if c["tool_error"] or c["result_type"] not in ("ok", None))
        rc = ", ".join((x.get("compiled_sql_sha256") or "")[:10] for x in r["receipts"]) or "none"
        lines.append(f"| {r['item']} | {r['arm']} | {r['seconds']} | {len(r['turns'])} | {len(r['tool_calls'])} ({fails}) | "
                     f"{r['loop_timeout']} | {round(ev / ed, 2) if ed else None} | {g['a']} | {g['b']} | {g['c']} | {g['d']} | "
                     f"{g['cell']} | {g['trap_sprung']} | {rc} |")
    if incomplete:
        lines += ["", "Incomplete (saved by a stop, not graded): " + ", ".join(f"{r['item']}/{r['arm']} ({r.get('stop_reason')})" for r in incomplete)]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--db", default=os.environ.get("ANALYTICSRECEIPTS_DB"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--prior-elapsed-s", type=float, default=0.0,
                    help="run time already used by earlier sessions of this queue (counts toward the 6 h / 7 h caps)")
    ap.add_argument("--prior-elapsed-note", default=None, help="how --prior-elapsed-s was derived (recorded)")
    a = ap.parse_args()
    if not a.db:
        raise SystemExit("--db or ANALYTICSRECEIPTS_DB is required")
    out = Path(a.out)
    if out.exists() and not a.resume:
        raise SystemExit(f"{out} already exists; pass --resume to continue it")
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config(a.config)
    if a.resume:
        starts = [r for r in read_jsonl(out) if r.get("event") == "start"]
        if starts and starts[0]["config_sha256"] != cfg["_sha256"]:
            raise SystemExit("config changed since the first run; refusing to resume")
    reason = anyio.run(run_live, cfg, a.db, str(out), a.resume, a.prior_elapsed_s, a.prior_elapsed_note)
    print("stop reason:", reason)


if __name__ == "__main__":
    main()
