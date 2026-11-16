"""Automatic scoring of math/logic (regex), code (unit tests in a subprocess), instruction following and
multi-turn checks, plus length checks for the summaries. Writes results/auto_scores.csv.
Rubric items (G*, S*) are scored separately by hand into results/rubric_scores.csv.
"""
import json, os, re, csv, subprocess, sys, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
CODEDIR = os.path.join(ROOT, "tmp", "codecheck")
os.makedirs(CODEDIR, exist_ok=True)
P = json.load(open(os.path.join(ROOT, "prompts.json"), encoding="utf-8"))
PROMPTS = {p["id"]: p for p in P["prompts"] + P["reasoning_extra"]}
ALT = {"R1": [5, 0.05]}  # 5 cents written as $0.05 also accepted
PY = sys.executable

NUM = r"-?\d+(?:,\d{3})*(?:\.\d+)?"


def clean(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    text = re.sub(r"<think>.*", "", text, flags=re.S | re.I)  # unclosed think block: nothing usable after it
    return text.strip()


def words(text):
    return len(re.findall(r"\b[\w'’-]+\b", text))


def final_segment(text):
    m = re.findall(r"final answer\s*[:：]?\s*(.+)", text, flags=re.I)
    return (m[-1], True) if m else (None, False)


def score_number(p, text):
    seg, fmt = final_segment(text)
    src = seg if seg is not None else text
    nums = re.findall(NUM, src.replace("$", ""))
    if not nums:
        return 0, f"no number (format_ok={fmt})"
    val = nums[0] if seg is not None else nums[-1]
    v = float(val.replace(",", ""))
    ok = any(abs(v - a) < 1e-6 for a in ALT.get(p["id"], [p["answer"]]))
    return int(ok), f"got {val} (format_ok={fmt})"


def score_word(p, text):
    seg, fmt = final_segment(text)
    src = (seg if seg is not None else text[-200:]).lower()
    others = [n for n in ("alice", "bob", "dave") if n in src]
    ok = p["answer"] in src and not others
    return int(ok), f"segment={src.strip()[:60]!r} (format_ok={fmt})"


def extract_code(text, func):
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.S | re.I)
    for b in blocks:
        if f"def {func}" in b:
            return b
    if f"def {func}" in text:
        return text[text.index(f"def {func}"):] if not blocks else blocks[0]
    return None


def score_code(p, text, tag):
    code = extract_code(text, p["func"])
    if not code:
        return 0, "no function found"
    name = hashlib.md5((tag + text).encode()).hexdigest()[:10]
    path = os.path.join(CODEDIR, f"{p['id']}_{name}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code + "\n\n" + "\n".join(p["tests"]) + "\nprint('ALL_TESTS_PASSED')\n")
    try:
        r = subprocess.run([PY, "-I", path], capture_output=True, text=True, timeout=10, cwd=CODEDIR)
        ok = "ALL_TESTS_PASSED" in r.stdout
        err = (r.stderr.strip().splitlines() or [""])[-1][:120]
        return int(ok), "pass" if ok else f"fail: {err}"
    except subprocess.TimeoutExpired:
        return 0, "timeout"


def score_instruction(p, text):
    s = p["scoring"]
    if s == "exact_bullets":
        lines = [l for l in text.splitlines() if l.strip()]
        bullets = [l for l in lines if re.match(r"^\s*([-*•+]|\d+[.)])\s+", l)]
        ok = len(bullets) == p["n"] and len(lines) == p["n"]
        return int(ok), f"{len(bullets)} bullets / {len(lines)} lines"
    if s == "json_only":
        strict = lenient = False
        try:
            j = json.loads(text.strip()); strict = True
        except Exception:
            j = None
            t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
            try:
                j = json.loads(t); lenient = True
            except Exception:
                pass
        shape = (isinstance(j, dict) and isinstance(j.get("name"), str) and isinstance(j.get("year"), int)
                 and isinstance(j.get("tags"), list) and len(j["tags"]) == 3 and all(isinstance(x, str) for x in j["tags"]))
        return int(strict and shape), f"strict_json={strict} fenced_json={lenient} shape_ok={shape}"
    if s == "max_words":
        n = words(text)
        return int(0 < n <= p["max_words"]), f"{n} words"
    if s == "keyword_and_end":
        has = p["keyword"] in text.lower()
        end = bool(re.search(r"\bEND[.!]?\s*$", text))
        return int(has and end), f"keyword={has} ends_with_END={end}"
    if s == "all_lowercase":
        ok = text == text.lower() and words(text) >= p["min_words"]
        return int(ok), f"lowercase={text == text.lower()} words={words(text)}"
    if s == "contains_short":
        ok = p["answer"] in text and words(text) <= p["max_words"]
        return int(ok), f"contains={p['answer'] in text} words={words(text)}"
    raise ValueError(s)


def score(row):
    p = PROMPTS[row["prompt_id"]]
    text = clean(row.get("content", ""))
    if row.get("error"):
        return 0, "error: " + row["error"][:80]
    s = p["scoring"]
    if s == "regex_number":
        return score_number(p, text)
    if s == "regex_word":
        return score_word(p, text)
    if s == "unit_tests":
        return score_code(p, text, row["tag"])
    if s.startswith("rubric+max_words"):
        n = words(text)
        return int(0 < n <= p["max_words"]), f"length check: {n} words (limit {p['max_words']})"
    if s == "rubric":
        return None, "rubric (scored by hand)"
    return score_instruction(p, text)


def main():
    rows = [json.loads(l) for l in open(os.path.join(RES, "raw_answers.jsonl"), encoding="utf-8")]
    latest = {}
    for r in rows:
        if r["phase"] in ("quality", "reason_off", "reason_on"):
            latest[(r["model"], r["profile"], r["phase"], r["prompt_id"])] = r
    out = []
    for (m, prof, phase, pid), r in sorted(latest.items()):
        sc, detail = score(r)
        raw = r.get("content", "") or ""
        out.append(dict(model=m, profile=prof, phase=phase, prompt_id=pid, category=PROMPTS[pid]["category"],
                        scoring=PROMPTS[pid]["scoring"], score="" if sc is None else sc, detail=detail,
                        had_think_tags=int("<think>" in raw.lower()), eval_count=r.get("eval_count"),
                        done_reason=r.get("done_reason")))
    with open(os.path.join(RES, "auto_scores.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    print(f"scored {len(out)} answers")


if __name__ == "__main__":
    main()
