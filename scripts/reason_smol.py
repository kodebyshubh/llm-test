"""Supplementary reasoning-mode run for SmolLM3-3B, Profile B settings (CPU only, 14 threads, all CPUs).
Ollama's `think` flag produced no thinking for this GGUF, so extended thinking is requested the way the
SmolLM3 model card documents: a /think flag in the system prompt. The earlier reason_on rows for smollm3_3b
are moved to superseded_rows.jsonl first."""
import json, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench
from bench import P, SYSTEM, RAW, RES, API, chat, start_server, pull, unload, append_jsonl, log, quiet_check, time

KEY, TAG = "smollm3_3b", "hf.co/ggml-org/SmolLM3-3B-GGUF:Q4_K_M"

rows = [json.loads(l) for l in open(RAW, encoding="utf-8")]
keep = []
with open(os.path.join(RES, "superseded_rows.jsonl"), "a", encoding="utf-8") as sup:
    for r in rows:
        if r["model"] == KEY and r["phase"] == "reason_on":
            r["_superseded_reason"] = "Ollama think flag produced no thinking for this GGUF; re-run with /think system flag"
            r["_source_file"] = "raw_answers.jsonl"
            sup.write(json.dumps(r, ensure_ascii=False) + "\n")
        else:
            keep.append(json.dumps(r, ensure_ascii=False) + "\n")
open(RAW, "w", encoding="utf-8").writelines(keep)

start_server(None, f"{KEY}-reason2")
pull(TAG)
cfg = bench.PROFILES["B"]
opts = dict(temperature=0, seed=bench.SEED, num_ctx=4096, num_gpu=cfg["num_gpu"], num_thread=cfg["num_thread"])
log(f"[{KEY} B reason2] quiet check: {quiet_check()}"); time.sleep(bench.COOLDOWN_S)
unload(TAG)
chat(TAG, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": P["warmup"]}], opts, 32)
rset = [p for p in P["prompts"] if p["category"] in ("math", "logic")] + P["reasoning_extra"]
for p in rset:
    msgs = [{"role": "system", "content": "/think\n" + SYSTEM}, {"role": "user", "content": p["prompt"]}]
    res = chat(TAG, msgs, opts, bench.NUM_PREDICT_THINK)
    res["error"] = None; res["note"] = "thinking requested with /think system flag"
    append_jsonl(RAW, dict(ts=datetime.datetime.now().isoformat(timespec="seconds"), model=KEY, tag=TAG, profile="B",
                           phase="reason_on", prompt_id=p["id"], repeat=0, options=opts, think="sysflag", **res))
    log(f"  B reason_on(/think) {p['id']}: {res['eval_count']} tok @ {res['tps']} tok/s, think_tag={'<think>' in res['content']}, done={res['done_reason']}")
unload(TAG)
start_server(None, f"{KEY}-rm2")
import requests
requests.delete(API + "/api/delete", json={"model": TAG}, timeout=60)
log(f"[{KEY}] reason2 done and model removed")
