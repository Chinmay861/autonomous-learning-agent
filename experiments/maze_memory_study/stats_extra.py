import json
import statistics
from pathlib import Path

import numpy as np
from scipy import stats

BASE = Path(__file__).resolve().parent
A = json.loads((BASE / "results" / "maze5_A" / "study_summary.json").read_text(encoding="utf-8"))["episodes"]
B = json.loads((BASE / "results" / "maze5_B" / "study_summary.json").read_text(encoding="utf-8"))["episodes"]

train_a = [e for e in A if "train" in e["episode_label"]]
train_b = [e for e in B if "train" in e["episode_label"]]
eval_a = [e for e in A if "eval" in e["episode_label"]][0]
eval_b = [e for e in B if "eval" in e["episode_label"]][0]

def col(eps, fn):
    return [fn(e) for e in eps]

metrics = {
    "moves": lambda e: e["env"]["moves_used"],
    "duration_s": lambda e: e["duration_s"],
    "total_tokens": lambda e: e["llm"]["total_tokens"],
    "prompt_tokens": lambda e: e["llm"]["prompt_tokens"],
    "completion_tokens": lambda e: e["llm"]["completion_tokens"],
    "llm_calls": lambda e: e["llm"]["calls"],
    "avg_latency_s": lambda e: e["llm"]["avg_latency_s"],
    "path_efficiency": lambda e: e["derived"]["path_efficiency"],
    "invalid_moves": lambda e: e["env"]["invalid_moves"],
}

print("=== paired stats (train episodes, same maze seeds both arms) ===")
for name, fn in metrics.items():
    va = col(train_a, fn)
    vb = col(train_b, fn)
    diff = np.array(vb, dtype=float) - np.array(va, dtype=float)
    t, p = stats.ttest_rel(vb, va)
    try:
        w, wp = stats.wilcoxon(vb, va)
    except Exception:
        w, wp = float("nan"), float("nan")
    print(f"{name:16s} A={np.mean(va):10.2f} B={np.mean(vb):10.2f} "
          f"d={diff.mean():9.2f} t={t:6.2f} p={p:.3f} wilcoxon_p={wp:.3f}")

print("\n=== trends (slope per episode) ===")
for name, fn in metrics.items():
    va = np.array(col(train_a, fn), dtype=float)
    vb = np.array(col(train_b, fn), dtype=float)
    x = np.arange(1, 6)
    sa = np.polyfit(x, va, 1)[0]
    sb = np.polyfit(x, vb, 1)[0]
    print(f"{name:16s} A slope={sa:9.2f}  B slope={sb:9.2f}")

print("\n=== early (ep1-2) vs late (ep4-5) ===")
for label, eps in (("A", train_a), ("B", train_b)):
    early = [e["env"]["moves_used"] for e in eps[:2]]
    late = [e["env"]["moves_used"] for e in eps[3:5]]
    early_d = [e["duration_s"] for e in eps[:2]]
    late_d = [e["duration_s"] for e in eps[3:5]]
    print(f"{label}: moves early={early} late={late} | dur early={[round(d) for d in early_d]} late={[round(d) for d in late_d]}")

print("\n=== B memory utilization ===")
retrieved = [e["memory"]["retrieved_total"] for e in train_b]
with_mem = [e["memory"]["iterations_with_memory"] for e in train_b]
print("retrieved per episode:", retrieved, "| total:", sum(retrieved))
print("iterations_with_memory per episode:", with_mem)
mem = [json.loads(l) for l in open(BASE / "results" / "maze5_B" / "memory.jsonl", encoding="utf-8")]
retr = [m for m in mem if m["type"] == "retrieval"]
ids = [i for m in retr for i in m.get("ids", [])]
print("retrieval calls:", len(retr), "| id slots returned:", len(ids), "| unique ids:", len(set(ids)))
scores = [s for m in retr for s in m.get("scores", [])]
print("similarity scores: n=%d mean=%.3f median=%.3f min=%.3f max=%.3f" % (
    len(scores), statistics.mean(scores), statistics.median(scores), min(scores), max(scores)))
norm = [m for m in mem if m["type"] == "synthesis_normalize"]
print("synthesis normalize calls:", len(norm), "| units:", [m.get("units") for m in norm])
writes = [m for m in mem if m["type"] == "write"]
print("memory write ops:", len(writes), "| inserts:", sum(1 for w in writes if w["op"] == "insert"),
      "| merges:", sum(1 for w in writes if w["op"] == "merge"))

print("\n=== notional API cost (DeepSeek V4.1 Flash off-peak $0.15/M in, $0.60/M out) ===")
for label, eps in (("A", train_a), ("B", train_b)):
    pin = sum(e["llm"]["prompt_tokens"] for e in eps)
    pout = sum(e["llm"]["completion_tokens"] for e in eps)
    cost = pin / 1e6 * 0.15 + pout / 1e6 * 0.60
    print(f"{label}: prompt={pin} completion={pout} -> ${cost:.3f} (5 train episodes)")

print("\n=== unseen eval episode ===")
for label, e in (("A", eval_a), ("B", eval_b)):
    print(f"{label}: success={e['success']} moves={e['env']['moves_used']} optimal={e['env']['optimal_moves']} "
          f"invalid={e['env']['invalid_moves']} iters={e['iterations_used']} dur={e['duration_s']:.0f}s "
          f"tokens={e['llm']['total_tokens']} retrieved={e['memory']['retrieved_total']} writes={e['memory']['store_calls']}")
