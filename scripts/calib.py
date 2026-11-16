"""Older-laptop speed ESTIMATES from the Llama 3.2 3B calibration. Writes results/calibration.csv.
factor = published tok/s of llama3.2:3b on the reference CPU / measured Profile A tok/s of llama3.2:3b here.
estimate(model) = measured Profile A tok/s(model) x factor. These are estimates, not measurements."""
import csv, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
rows = [r for r in csv.DictReader(open(os.path.join(RES, "results.csv"), encoding="utf-8")) if r["profile"] == "A"]
llama = float(next(r for r in rows if r["model"] == "llama32_3b")["tps_median"])
REF = {"N150 (Geerling, verified)": 9.06, "i5-10210U (MetriLLM, unverified)": 10.0}
out = []
for r in rows:
    a = float(r["tps_median"])
    d = dict(model=r["model"], name=r["name"], profileA_tps=a)
    for k, v in REF.items():
        d[f"factor {k}"] = round(v / llama, 3)
        d[f"est tps {k}"] = round(a * v / llama, 1)
    out.append(d)
with open(os.path.join(RES, "calibration.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
for d in out:
    print(d)
