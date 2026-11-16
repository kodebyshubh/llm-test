"""Moves rows taken while a stray sampler forced 4-CPU affinity into results/superseded_rows.jsonl and resets
state so those runs are repeated. Affected: nemotron3_4b profiles B and C, all smollm3_3b rows.
Kept for traceability; nothing is deleted."""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")


def bad(r):
    return (r["model"] == "nemotron3_4b" and r["profile"] in ("B", "C")) or r["model"] == "smollm3_3b"


for name in ("raw_answers.jsonl", "profile_meta.jsonl"):
    path = os.path.join(RES, name)
    keep, moved = [], 0
    with open(os.path.join(RES, "superseded_rows.jsonl"), "a", encoding="utf-8") as sup:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if bad(r):
                r["_superseded_reason"] = "stray sampler thread forced CPU affinity 0,2,4,6 (bug fixed 2026-11-15 15:45)"
                r["_source_file"] = name
                sup.write(json.dumps(r, ensure_ascii=False) + "\n"); moved += 1
            else:
                keep.append(line)
    open(path, "w", encoding="utf-8").writelines(keep)
    print(name, "moved", moved, "kept", len(keep))

st = json.load(open(os.path.join(RES, "state.json"), encoding="utf-8"))
n = st["nemotron3_4b"]
for k in ("B", "C", "removed"):
    n.pop(k, None)
n["pulled"] = False
st.pop("smollm3_3b", None)
json.dump(st, open(os.path.join(RES, "state.json"), "w", encoding="utf-8"), indent=2)
print("state reset for nemotron3_4b B/C and smollm3_3b")
