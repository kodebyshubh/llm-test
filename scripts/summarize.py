"""Builds results/results.csv (one row per model and profile) from raw_answers.jsonl, profile_meta.jsonl,
state.json, auto_scores.csv and rubric_scores.csv. Every number in the report traces back to this file."""
import json, os, csv, statistics
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
MODELS = json.load(open(os.path.join(ROOT, "models.json"), encoding="utf-8"))
STATE = json.load(open(os.path.join(RES, "state.json"), encoding="utf-8"))
P = json.load(open(os.path.join(ROOT, "prompts.json"), encoding="utf-8"))

raw = [json.loads(l) for l in open(os.path.join(RES, "raw_answers.jsonl"), encoding="utf-8")]
meta = {}
for l in open(os.path.join(RES, "profile_meta.jsonl"), encoding="utf-8"):
    m = json.loads(l); meta[(m["model"], m["profile"])] = m  # last one wins

auto = defaultdict(dict)
if os.path.exists(os.path.join(RES, "auto_scores.csv")):
    for r in csv.DictReader(open(os.path.join(RES, "auto_scores.csv"), encoding="utf-8")):
        auto[(r["model"], r["profile"], r["phase"])][r["prompt_id"]] = r
rubric = defaultdict(dict)
if os.path.exists(os.path.join(RES, "rubric_scores.csv")):
    for r in csv.DictReader(open(os.path.join(RES, "rubric_scores.csv"), encoding="utf-8")):
        rubric[r["model"]][r["prompt_id"]] = int(r["score"])

CAT = {p["id"]: p["category"] for p in P["prompts"] + P["reasoning_extra"]}


def rows_for(m, prof, phase):
    return [r for r in raw if r["model"] == m and r["profile"] == prof and r["phase"] == phase and not r.get("error")]


def tps(r):
    return r["eval_count"] / (r["eval_duration"] / 1e9) if r.get("eval_count") and r.get("eval_duration") else None


def fit_label(gb):
    if gb is None:
        return ""
    return "yes" if gb <= 3.0 else ("tight" if gb <= 4.5 else "no")


def catscore(m, prof, phase, cats):
    d = auto.get((m, prof, phase), {})
    xs = [int(v["score"]) for k, v in d.items() if CAT[k] in cats and v["score"] != ""]
    return f"{sum(xs)}/{len(xs)}" if xs else ""


out = []
for mm in MODELS:
    k = mm["key"]; st = STATE.get(k, {}); info = st.get("info", {})
    for prof in ("A", "B", "C"):
        mt = meta.get((k, prof))
        sp = rows_for(k, prof, "speed")
        if not mt and not sp:
            continue
        sps = [tps(r) for r in sp if tps(r)]
        reps = {rep: [tps(r) for r in sp if r["repeat"] == rep and tps(r)] for rep in (1, 2, 3)}
        rep_mean = {rep: (statistics.mean(v) if v else None) for rep, v in reps.items()}
        lg = rows_for(k, prof, "long")
        lg = lg[-1] if lg else {}
        q = rows_for(k, prof, "quality")
        qt = [tps(r) for r in q if tps(r)]
        ron = rows_for(k, prof, "reason_on")
        # a reasoning run only counts if the model actually produced thinking (thinking field or <think> tags)
        think_produced = any((r.get("thinking") or "").strip() or "<think>" in (r.get("content") or "").lower() for r in ron)
        if ron and not think_produced:
            ron = []
        # reasoning token cost: same 8 prompts, think on vs off (off = quality M1-M4 + reason_off R1-R4, profile B)
        off_rows = [r for r in q if CAT.get(r["prompt_id"]) in ("math", "logic")] + rows_for(k, prof, "reason_off")
        row = dict(
            model=k, name=mm["name"], developer=mm["dev"], tag=mm["tag"], profile=prof,
            params=info.get("param_count"), param_label=info.get("details", {}).get("parameter_size"),
            quant=info.get("details", {}).get("quantization_level"), ctx_max=info.get("context_length"),
            download_gb=round(info["size_bytes"] / 1e9, 2) if info.get("size_bytes") else None,
            capabilities="|".join(info.get("capabilities", [])),
            num_thread=(mt or {}).get("options", {}).get("num_thread"), num_gpu=(mt or {}).get("options", {}).get("num_gpu"),
            affinity_seen=json.dumps((mt or {}).get("affinities_seen")),
            cold_load_s=(mt or {}).get("cold_load_s"),
            tps_median=round(statistics.median(sps), 2) if sps else None,
            tps_min=round(min(sps), 2) if sps else None, tps_max=round(max(sps), 2) if sps else None, tps_n=len(sps),
            tps_rep1=round(rep_mean[1], 2) if rep_mean[1] else None, tps_rep2=round(rep_mean[2], 2) if rep_mean[2] else None,
            tps_rep3=round(rep_mean[3], 2) if rep_mean[3] else None,
            thermal_change_pct=round(100 * (rep_mean[3] - rep_mean[1]) / rep_mean[1], 1) if rep_mean[1] and rep_mean[3] else None,
            quality_tps_median=round(statistics.median(qt), 2) if qt else None,
            quality_tokens_total=sum(r.get("eval_count") or 0 for r in q) if q else None,
            long_prompt_tokens=lg.get("prompt_eval_count"),
            long_prompt_tps=round(lg["prompt_eval_count"] / (lg["prompt_eval_duration"] / 1e9), 1) if lg.get("prompt_eval_duration") else None,
            long_ttft_s=lg.get("ttft_s"),
            long_answer=(lg.get("content") or "").strip()[:20], long_answer_expected=P["long_prompt"]["answer"],
            peak_ram_gb=(mt or {}).get("peak_rss_gb"), peak_private_gb=(mt or {}).get("peak_private_gb"),
            peak_runner_ram_gb=(mt or {}).get("peak_runner_rss_gb"), min_sys_avail_gb=(mt or {}).get("min_system_available_gb"),
            peak_vram_mb=(mt or {}).get("peak_vram_mb"), vram_baseline_mb=(mt or {}).get("vram_baseline_mb"),
            gpu_procs=json.dumps((mt or {}).get("gpu_ollama_procs")),
            fits_8gb=fit_label((mt or {}).get("peak_rss_gb")) if prof == "A" else "",
            under_8gb=((mt or {}).get("peak_rss_gb") or 99) < 8 if prof == "A" and mt else "",
            under_4gb=((mt or {}).get("peak_rss_gb") or 99) < 4 if prof == "A" and mt else "",
            math_logic=catscore(k, prof, "quality", {"math", "logic"}), code=catscore(k, prof, "quality", {"code"}),
            instruction=catscore(k, prof, "quality", {"instruction"}), multiturn=catscore(k, prof, "quality", {"multiturn"}),
            summary_length=catscore(k, prof, "quality", {"summarization"}),
            rubric_total=(sum(rubric[k].values()) if rubric.get(k) and prof == "A" else ""),
            rubric_max=(2 * len(rubric[k]) if rubric.get(k) and prof == "A" else ""),
            reason_off_8=(catscore(k, prof, "quality", {"math", "logic"}) and
                          f"{sum(int(v['score']) for kk, v in {**auto.get((k, prof, 'quality'), {}), **auto.get((k, prof, 'reason_off'), {})}.items() if CAT[kk] in ('math', 'logic'))}/8") if prof == "B" else "",
            reason_on_8=(catscore(k, prof, "reason_on", {"math", "logic"}) if ron else
                         ("no thinking produced" if rows_for(k, prof, "reason_on") else "")) if prof == "B" else "",
            think_tokens_mean_on=round(statistics.mean([r["eval_count"] for r in ron]), 0) if ron else None,
            think_tokens_mean_off=round(statistics.mean([r["eval_count"] for r in off_rows if r.get("eval_count")]), 0) if ron and off_rows else None,
            think_tps_median=round(statistics.median([tps(r) for r in ron if tps(r)]), 2) if ron else None,
            think_truncated=sum(1 for r in ron if r.get("done_reason") == "length") if ron else None,
            status=st.get(prof, ""),
        )
        out.append(row)

with open(os.path.join(RES, "results.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)
print(f"results.csv: {len(out)} rows")
