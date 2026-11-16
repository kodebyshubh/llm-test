"""Resumable benchmark pipeline: for each model: pull -> Profile A -> Profile B (+reasoning) -> Profile C -> remove.
Only one model and one timed measurement at a time. All writes stay inside ROOT.
Usage: python -I bench.py [model_key ...]
"""
import json, os, sys, time, shutil, threading, subprocess, datetime, statistics, traceback
import psutil, requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
LOGS = os.path.join(ROOT, "logs")
TMP = os.path.join(ROOT, "tmp")
# Path to ollama.exe: OLLAMA_EXE env var, else whatever is on PATH, else the default Windows install location.
OLLAMA_EXE = (os.environ.get("OLLAMA_EXE") or shutil.which("ollama")
              or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"))
API = "http://127.0.0.1:11434"
RAW = os.path.join(RES, "raw_answers.jsonl")
META = os.path.join(RES, "profile_meta.jsonl")
STATE = os.path.join(RES, "state.json")
LOG = os.path.join(LOGS, "bench.log")

A_CPUS = [0, 2, 4, 6]  # one logical CPU on each of four different P-cores (P-core HT pairs are 0/1, 2/3, ...)
PROFILES = {
    "A": dict(num_gpu=0, num_thread=4, affinity=A_CPUS, full=True, reasoning=False, gpu_interval=2.0),
    "B": dict(num_gpu=0, num_thread=14, affinity=None, full=True, reasoning=True, gpu_interval=2.0),
    "C": dict(num_gpu=999, num_thread=None, affinity=None, full=False, reasoning=False, gpu_interval=0.5),
}
NUM_PREDICT = 512
NUM_PREDICT_CODE = 1024
NUM_PREDICT_SPEED = 256
NUM_PREDICT_THINK = 3072
SEED = 42
COOLDOWN_S = 20

os.makedirs(RES, exist_ok=True); os.makedirs(LOGS, exist_ok=True); os.makedirs(TMP, exist_ok=True)
P = json.load(open(os.path.join(ROOT, "prompts.json"), encoding="utf-8"))
SYSTEM = P["system"]


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {}


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), indent=2)
    os.replace(tmp, STATE)


def done_keys():
    keys = set()
    if os.path.exists(RAW):
        for line in open(RAW, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("error") and r["phase"] != "warmup":
                keys.add((r["model"], r["profile"], r["phase"], r["prompt_id"], r.get("repeat", 0)))
    return keys


# ---------------- server control ----------------
def is_ollama_proc(name, include_app=False):
    n = (name or "").lower()
    if n.startswith("llama-server"):  # Ollama 0.40 model runner (lib\ollama\llama-server.exe)
        return True
    return n.startswith("ollama") and (include_app or "app" not in n)


def kill_ollama():
    for p in psutil.process_iter(["name"]):
        if is_ollama_proc(p.info["name"], include_app=True):
            try:
                p.kill()
            except psutil.Error:
                pass
    time.sleep(2)


def start_server(affinity=None, tag=""):
    kill_ollama()
    for t in threading.enumerate():  # safety net: no stray sampler may survive into a new profile
        if isinstance(t, Sampler) and t.is_alive():
            log("  WARNING: stopping stray sampler thread"); t.stop()
    env = dict(os.environ)
    env.update(OLLAMA_MODELS=os.path.join(ROOT, "ollama-models"), TEMP=TMP, TMP=TMP, OLLAMA_VULKAN="false",
               OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_KEEP_ALIVE="30m")
    lf = open(os.path.join(LOGS, f"serve-{tag or 'x'}.log"), "a", encoding="utf-8")
    proc = subprocess.Popen([OLLAMA_EXE, "serve"], env=env, stdout=lf, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    if affinity is not None:
        psutil.Process(proc.pid).cpu_affinity(affinity)  # children (model runners) inherit this mask
    for _ in range(60):
        try:
            requests.get(API + "/api/version", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    aff = psutil.Process(proc.pid).cpu_affinity()
    want = affinity if affinity is not None else list(range(psutil.cpu_count()))
    if sorted(aff) != sorted(want):
        raise RuntimeError(f"server affinity {aff} does not match requested {want}")
    log(f"server started pid={proc.pid} affinity={aff if affinity is not None else 'all (' + str(len(aff)) + ' cpus)'}")
    return proc


def unload(tag):
    try:
        requests.post(API + "/api/generate", json={"model": tag, "keep_alive": 0}, timeout=120)
    except Exception as e:
        log(f"unload error {e}")
    for _ in range(60):
        try:
            if not requests.get(API + "/api/ps", timeout=5).json().get("models"):
                return
        except Exception:
            pass
        time.sleep(0.5)


def pull(tag):
    log(f"pull {tag} start")
    t0 = time.time(); last = -1; status = None
    with requests.post(API + "/api/pull", json={"model": tag, "stream": True}, stream=True, timeout=(10, 3600)) as r:
        for line in r.iter_lines():
            if not line:
                continue
            j = json.loads(line)
            if "error" in j:
                raise RuntimeError(j["error"])
            status = j.get("status")
            if j.get("total") and j.get("completed"):
                pct = int(100 * j["completed"] / j["total"]) // 20 * 20
                if pct != last:
                    last = pct; log(f"  pull {tag} {status} {pct}% of {j['total'] / 1e9:.2f} GB")
    if status != "success":
        raise RuntimeError(f"pull ended with status {status}")
    log(f"pull {tag} done in {time.time() - t0:.0f}s")
    return time.time() - t0


def model_info(tag):
    tags = requests.get(API + "/api/tags", timeout=10).json()["models"]
    size = next((m["size"] for m in tags if m["name"] == tag or m["model"] == tag), None)
    sh = requests.post(API + "/api/show", json={"model": tag}, timeout=30).json()
    mi = sh.get("model_info", {})
    ctx = next((v for k, v in mi.items() if k.endswith(".context_length")), None)
    lic = (sh.get("license") or "").strip().splitlines()
    return dict(size_bytes=size, capabilities=sh.get("capabilities", []), details=sh.get("details", {}),
                context_length=ctx, license_head=" ".join(lic[:3])[:300], param_count=mi.get("general.parameter_count"))


# ---------------- sampler ----------------
class Sampler(threading.Thread):
    def __init__(self, gpu_interval, affinity=None):
        super().__init__(daemon=True)
        self.gpu_interval, self.affinity = gpu_interval, affinity
        self.stop_evt = threading.Event()
        self.peak_rss = self.peak_priv = self.peak_runner = 0
        self.min_avail = float("inf")
        self.peak_vram = 0; self.vram_samples = 0; self.gpu_procs = set()
        self.affinities = set(); self.fixes = 0
        self.cpu_acc = None; self.cpu_n = 0

    def run(self):
        last_gpu = 0
        psutil.cpu_percent(percpu=True)
        while not self.stop_evt.is_set():
            rss = priv = run_rss = 0
            for p in psutil.process_iter(["name"]):
                if not is_ollama_proc(p.info["name"]):
                    continue
                try:
                    mi = p.memory_info(); rss += mi.rss; priv += getattr(mi, "private", 0)
                    if (p.info["name"] or "").lower().startswith("llama-server"):
                        run_rss += mi.rss
                    a = p.cpu_affinity()
                    if self.affinity is not None and sorted(a) != sorted(self.affinity):
                        p.cpu_affinity(self.affinity); self.fixes += 1
                        log(f"  sampler: fixed affinity of pid {p.pid} from {a} to {self.affinity}")
                        a = p.cpu_affinity()
                    self.affinities.add(tuple(a) if len(a) < 20 else ("all",))
                except psutil.Error:
                    pass
            self.peak_rss = max(self.peak_rss, rss); self.peak_priv = max(self.peak_priv, priv)
            self.peak_runner = max(self.peak_runner, run_rss)
            self.min_avail = min(self.min_avail, psutil.virtual_memory().available)
            pc = psutil.cpu_percent(percpu=True)
            self.cpu_acc = pc if self.cpu_acc is None else [x + y for x, y in zip(self.cpu_acc, pc)]
            self.cpu_n += 1
            now = time.time()
            if now - last_gpu >= self.gpu_interval:
                last_gpu = now
                try:
                    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                       capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.peak_vram = max(self.peak_vram, int(o.stdout.strip().splitlines()[0])); self.vram_samples += 1
                    o = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
                                       capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    for ln in o.stdout.strip().splitlines():
                        if "ollama" in ln.lower() or "llama-server" in ln.lower():
                            self.gpu_procs.add(ln.strip())
                except Exception:
                    pass
            self.stop_evt.wait(0.5)

    def stop(self):
        self.stop_evt.set(); self.join(10)
        avg = [round(x / max(self.cpu_n, 1), 1) for x in (self.cpu_acc or [])]
        return dict(peak_rss_gb=round(self.peak_rss / 1e9, 3), peak_private_gb=round(self.peak_priv / 1e9, 3),
                    peak_runner_rss_gb=round(self.peak_runner / 1e9, 3),
                    min_system_available_gb=round(self.min_avail / 1e9, 2) if self.min_avail != float("inf") else None,
                    peak_vram_mb=self.peak_vram, vram_samples=self.vram_samples, gpu_ollama_procs=sorted(self.gpu_procs),
                    affinities_seen=[list(a) for a in self.affinities], affinity_fixes=self.fixes, avg_cpu_percent_per_logical=avg)


def vram_now():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        return int(o.stdout.strip().splitlines()[0])
    except Exception:
        return None


def quiet_check():
    procs = list(psutil.process_iter(["name"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    tot = psutil.cpu_percent(interval=3)
    top = []
    for p in procs:
        try:
            top.append((p.cpu_percent(None), p.info["name"]))
        except psutil.Error:
            pass
    top.sort(reverse=True)
    vm = psutil.virtual_memory()
    return dict(cpu_total_pct_3s=tot, top_procs=[f"{n}:{c:.0f}%" for c, n in top[:5]],
                ram_available_gb=round(vm.available / 1e9, 2), ram_total_gb=round(vm.total / 1e9, 2))


# ---------------- API calls ----------------
def chat(tag, messages, opts, num_predict, think=None, stream=False):
    body = dict(model=tag, messages=messages, stream=stream, keep_alive="30m",
                options=dict(opts, num_predict=num_predict))
    if think is not None:
        body["think"] = think
    t0 = time.time(); ttft = None; content = []; thinking = []; final = None
    if not stream:
        r = requests.post(API + "/api/chat", json=body, timeout=(10, 3600))
        j = r.json()
        if "error" in j:
            raise RuntimeError(j["error"])
        final = j; content = [j["message"].get("content", "")]; thinking = [j["message"].get("thinking", "") or ""]
    else:
        with requests.post(API + "/api/chat", json=body, stream=True, timeout=(10, 3600)) as r:
            for line in r.iter_lines():
                if not line:
                    continue
                j = json.loads(line)
                if "error" in j:
                    raise RuntimeError(j["error"])
                m = j.get("message", {})
                if ttft is None and (m.get("content") or m.get("thinking")):
                    ttft = time.time() - t0
                content.append(m.get("content", "")); thinking.append(m.get("thinking", "") or "")
                if j.get("done"):
                    final = j
    wall = time.time() - t0
    g = lambda k: final.get(k)
    return dict(content="".join(content), thinking="".join(thinking), wall_s=round(wall, 3),
                ttft_s=round(ttft, 3) if ttft is not None else None,
                eval_count=g("eval_count"), eval_duration=g("eval_duration"),
                prompt_eval_count=g("prompt_eval_count"), prompt_eval_duration=g("prompt_eval_duration"),
                load_duration=g("load_duration"), total_duration=g("total_duration"), done_reason=g("done_reason"),
                tps=round(g("eval_count") / (g("eval_duration") / 1e9), 3) if g("eval_count") and g("eval_duration") else None)


def messages_for(p):
    msgs = [{"role": "system", "content": p.get("system", SYSTEM)}]
    msgs += p.get("history", [])
    msgs.append({"role": "user", "content": p["prompt"]})
    return msgs


# ---------------- profile run ----------------
def run_profile(mkey, tag, prof, info, st):
    cfg = PROFILES[prof]
    srv = start_server(cfg["affinity"], f"{mkey}-{prof}")
    opts = dict(temperature=0, seed=SEED, num_ctx=4096, num_gpu=cfg["num_gpu"])
    if cfg["num_thread"]:
        opts["num_thread"] = cfg["num_thread"]
    can_think = "thinking" in info.get("capabilities", [])
    think_off = False if can_think else None
    done = done_keys()

    def rec(phase, pid, rep, res, extra=None):
        row = dict(ts=datetime.datetime.now().isoformat(timespec="seconds"), model=mkey, tag=tag, profile=prof,
                   phase=phase, prompt_id=pid, repeat=rep, options=opts, think=extra, **res)
        append_jsonl(RAW, row)
        return row

    def call(phase, pid, rep, msgs, npred, think, stream=False):
        if (mkey, prof, phase, pid, rep) in done:
            return None
        try:
            res = chat(tag, msgs, opts, npred, think, stream)
            res["error"] = None
        except Exception as e:
            # a model that rejects the think flag: retry once without it and note it
            if think is not None and "think" in str(e).lower():
                log(f"  {pid}: think flag rejected ({e}); retrying without it")
                res = chat(tag, msgs, opts, npred, None, stream); res["error"] = None; res["note"] = f"think flag rejected: {e}"
            else:
                log(f"  ERROR {phase} {pid} r{rep}: {e}")
                res = dict(error=str(e), content="", thinking="")
        row = rec(phase, pid, rep, res, think)
        if res.get("tps"):
            log(f"  {prof} {phase} {pid} r{rep}: {res['eval_count']} tok @ {res['tps']:.2f} tok/s, wall {res['wall_s']:.1f}s, done={res.get('done_reason')}")
        return row

    qc = quiet_check()
    log(f"[{mkey} {prof}] quiet check: {qc}")
    log(f"[{mkey} {prof}] cooldown {COOLDOWN_S}s")
    time.sleep(COOLDOWN_S)
    vbase = vram_now()
    unload(tag)
    sampler = Sampler(cfg["gpu_interval"], cfg["affinity"]); sampler.start()
    try:
        return _run_profile_body(mkey, tag, prof, cfg, opts, think_off, can_think, call, rec, sampler, qc, vbase, st)
    finally:
        if sampler.is_alive():  # never leave a sampler running: it would keep forcing affinity on later servers
            sampler.stop()


def _run_profile_body(mkey, tag, prof, cfg, opts, think_off, can_think, call, rec, sampler, qc, vbase, st):
    t_start = time.time()
    # warm-up = cold load measurement (model files likely in OS file cache)
    w = chat(tag, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": P["warmup"]}], opts, 32, think_off)
    w["error"] = None
    rec("warmup", "WARMUP", 0, w, think_off)
    cold_load_s = round((w["load_duration"] or 0) / 1e9, 3)
    log(f"[{mkey} {prof}] cold load {cold_load_s}s (wall {w['wall_s']}s)")
    # speed: 3 prompts x 3 repeats
    for rep in (1, 2, 3):
        for sp in P["speed"]:
            call("speed", sp["id"], rep, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": sp["prompt"]}],
                 NUM_PREDICT_SPEED, think_off)
    # long prompt: prompt processing speed and time to first token
    lp = P["long_prompt"]
    call("long", lp["id"], 0, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": lp["prompt"]}], 64, think_off, stream=True)
    if cfg["full"]:
        for p in P["prompts"]:
            npred = NUM_PREDICT_CODE if p["category"] == "code" else NUM_PREDICT
            call("quality", p["id"], 0, messages_for(p), npred, think_off)
    if cfg["reasoning"]:
        for p in P["reasoning_extra"]:
            call("reason_off", p["id"], 0, messages_for(p), NUM_PREDICT, think_off)
        if can_think:
            rset = [p for p in P["prompts"] if p["category"] in ("math", "logic")] + P["reasoning_extra"]
            for p in rset:
                call("reason_on", p["id"], 0, messages_for(p), NUM_PREDICT_THINK, True)
    mem = sampler.stop()
    unload(tag)
    meta = dict(ts=datetime.datetime.now().isoformat(timespec="seconds"), model=mkey, tag=tag, profile=prof,
                options=opts, affinity_requested=cfg["affinity"], cold_load_s=cold_load_s, cold_load_wall_s=w["wall_s"],
                vram_baseline_mb=vbase, duration_s=round(time.time() - t_start), quiet_check=qc, can_think=can_think, **mem)
    append_jsonl(META, meta)
    log(f"[{mkey} {prof}] done: peak RSS {mem['peak_rss_gb']} GB, private {mem['peak_private_gb']} GB, "
        f"VRAM peak {mem['peak_vram_mb']} MB (baseline {vbase}), affinities {mem['affinities_seen']}, gpu procs {mem['gpu_ollama_procs']}")
    st[mkey][prof] = "done"; save_state(st)


def run_model(m, st):
    mkey, tag = m["key"], m["tag"]
    st.setdefault(mkey, {"tag": tag})
    if st[mkey].get("removed"):
        log(f"[{mkey}] already complete, skipping"); return
    if st[mkey].get("failed"):
        log(f"[{mkey}] previously failed ({st[mkey]['failed']}), skipping"); return
    log(f"===== {mkey} ({tag}) =====")
    if not st[mkey].get("pulled"):
        start_server(None, f"{mkey}-pull")
        try:
            st[mkey]["pull_s"] = round(pull(tag))
        except Exception as e:
            log(f"[{mkey}] PULL FAILED: {e}")
            st[mkey]["failed"] = f"pull: {e}"; save_state(st); return
        st[mkey]["pulled"] = True
        st[mkey]["info"] = model_info(tag); save_state(st)
        log(f"[{mkey}] info: {st[mkey]['info']}")
        log(f"[{mkey}] disk: models folder {folder_gb():.2f} GB, C free {free_gb('C:')} GB, D free {free_gb('D:')} GB")
    for prof in ("A", "B", "C"):
        if st[mkey].get(prof) == "done":
            continue
        try:
            run_profile(mkey, tag, prof, st[mkey]["info"], st)
        except Exception as e:
            log(f"[{mkey} {prof}] PROFILE FAILED: {e}\n{traceback.format_exc()}")
            st[mkey][prof] = f"failed: {e}"; save_state(st)
    start_server(None, f"{mkey}-rm")
    requests.delete(API + "/api/delete", json={"model": tag}, timeout=60)
    st[mkey]["removed"] = True; save_state(st)
    log(f"[{mkey}] removed. models folder {folder_gb():.2f} GB, C free {free_gb('C:')} GB, D free {free_gb('D:')} GB")


def folder_gb():
    tot = 0
    for dp, _, fs in os.walk(os.path.join(ROOT, "ollama-models")):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot / 1e9


def free_gb(d):
    return round(psutil.disk_usage(d).free / 1e9, 2)


if __name__ == "__main__":
    models = json.load(open(os.path.join(ROOT, "models.json"), encoding="utf-8"))
    want = sys.argv[1:]
    st = load_state()
    log(f"bench start; models={want or 'all'}")
    for m in models:
        if want and m["key"] not in want:
            continue
        run_model(m, st)
        st = load_state()
    log("bench finished")
