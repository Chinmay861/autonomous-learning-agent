"""
Analysis for the 5x5 Persistent Maze Learning Benchmark study.

Reads results/maze5_A/study_summary.json (Persistence OFF) and
results/maze5_B/study_summary.json (Persistence ON), produces:
  - analysis/episode_metrics.csv
  - analysis/comparison.md   (comparative metrics tables, observed vs derived)
  - analysis/charts/*.png
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent


def load_summary(path: Path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("episodes", [])
    except Exception:
        return []


def row_from(ep: dict, arm: str) -> dict:
    e = ep.get("env", {}) or {}
    d = ep.get("derived", {}) or {}
    m = ep.get("memory", {}) or {}
    llm = ep.get("llm", {}) or {}
    http = ep.get("http", {}) or {}
    agent = ep.get("agent", {}) or {}
    return {
        "arm": arm,
        "episode": ep.get("episode"),
        "label": ep.get("episode_label"),
        "split": "eval" if "eval" in (ep.get("episode_label") or "") else "train",
        "success": 1 if ep.get("success") else 0,
        "moves_used": e.get("moves_used", 0),
        "steps": e.get("steps", 0),
        "optimal_moves": e.get("optimal_moves", 0),
        "excess_moves": (e.get("moves_used", 0) - e.get("optimal_moves", 0)),
        "invalid_moves": e.get("invalid_moves", 0),
        "repeated_moves": e.get("repeated_moves", 0),
        "trap_activations": e.get("trap_activations", 0),
        "cells_visited": e.get("cells_visited", 0),
        "cells_seen": e.get("cells_seen", 0),
        "path_efficiency": d.get("path_efficiency"),
        "exploration_efficiency": d.get("exploration_efficiency"),
        "iterations": ep.get("iterations_used", 0),
        "duration_s": ep.get("duration_s", 0.0),
        "llm_calls": llm.get("calls", 0),
        "llm_failed": llm.get("failed", 0),
        "llm_empty": llm.get("empty_content", 0),
        "prompt_tokens": llm.get("prompt_tokens") or 0,
        "completion_tokens": llm.get("completion_tokens") or 0,
        "reasoning_tokens": llm.get("reasoning_tokens") or 0,
        "total_tokens": llm.get("total_tokens") or 0,
        "avg_llm_latency_s": llm.get("avg_latency_s") or 0.0,
        "prompt_chars": llm.get("prompt_chars") or 0,
        "http_429": http.get("retries_429", 0),
        "retrieval_calls": m.get("retrieval_calls", 0),
        "retrieved_total": m.get("retrieved_total", 0),
        "iterations_with_memory": m.get("iterations_with_memory", 0),
        "writes_insert": m.get("writes_insert", 0),
        "writes_merge": m.get("writes_merge", 0),
        "store_calls": m.get("store_calls", 0),
        "points_after": m.get("points_after", 0),
        "learnings_created": agent.get("learnings_created", 0),
        "rule_updates": agent.get("rule_updates", 0),
        "known_rules_final": agent.get("known_rules_final", 0),
    }


def agg(rows, key):
    values = [r[key] for r in rows if r[key] is not None]
    if not values:
        return (None, None, None)
    mean = statistics.mean(values)
    med = statistics.median(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return (mean, med, sd)


def fmt(value, digits=2):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def trend_slope(rows, key):
    values = [(r["episode"], r[key]) for r in rows if r[key] is not None]
    if len(values) < 2:
        return None
    xs = np.array([v[0] for v in values], dtype=float)
    ys = np.array([v[1] for v in values], dtype=float)
    slope = np.polyfit(xs, ys, 1)[0]
    return float(slope)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir-a", default=str(HERE / "results" / "maze5_A"))
    parser.add_argument("--dir-b", default=str(HERE / "results" / "maze5_B"))
    parser.add_argument("--out", default=str(HERE / "analysis"))
    args = parser.parse_args()

    out_dir = Path(args.out)
    (out_dir / "charts").mkdir(parents=True, exist_ok=True)

    eps_a = load_summary(Path(args.dir_a) / "study_summary.json")
    eps_b = load_summary(Path(args.dir_b) / "study_summary.json")
    rows_a = [row_from(e, "A-OFF") for e in eps_a]
    rows_b = [row_from(e, "B-ON") for e in eps_b]
    all_rows = rows_a + rows_b

    # CSV
    if all_rows:
        with open(out_dir / "episode_metrics.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)

    train_a = [r for r in rows_a if r["split"] == "train"]
    train_b = [r for r in rows_b if r["split"] == "train"]
    eval_a = [r for r in rows_a if r["split"] == "eval"]
    eval_b = [r for r in rows_b if r["split"] == "eval"]

    metrics = [
        ("success_rate", "success", "Task success rate (0-1)"),
        ("moves_used", "moves_used", "Total moves"),
        ("excess_moves", "excess_moves", "Excess moves over optimal"),
        ("path_efficiency", "path_efficiency", "Path efficiency (optimal/actual)"),
        ("exploration_efficiency", "exploration_efficiency", "Exploration efficiency (useful/total)"),
        ("invalid_moves", "invalid_moves", "Invalid moves (blocked/invalid actions)"),
        ("repeated_moves", "repeated_moves", "Repeated moves (revisits)"),
        ("cells_visited", "cells_visited", "Cells visited"),
        ("cells_seen", "cells_seen", "Cells seen (map coverage)"),
        ("iterations", "iterations", "Agent iterations (actions)"),
        ("duration_s", "duration_s", "Episode duration (s)"),
        ("llm_calls", "llm_calls", "LLM calls"),
        ("llm_failed", "llm_failed", "Failed LLM calls"),
        ("llm_empty", "llm_empty", "LLM calls with empty content"),
        ("prompt_tokens", "prompt_tokens", "Prompt tokens"),
        ("completion_tokens", "completion_tokens", "Completion tokens"),
        ("reasoning_tokens", "reasoning_tokens", "Reasoning tokens"),
        ("total_tokens", "total_tokens", "Total tokens"),
        ("avg_llm_latency_s", "avg_llm_latency_s", "Avg LLM call latency (s)"),
        ("http_429", "http_429", "HTTP 429 retries"),
        ("retrieved_total", "retrieved_total", "Memories retrieved (total)"),
        ("iterations_with_memory", "iterations_with_memory", "Iterations with >=1 retrieved memory"),
        ("writes_insert", "writes_insert", "Memory writes (new inserts)"),
        ("writes_merge", "writes_merge", "Memory writes (dedup merges)"),
        ("points_after", "points_after", "Vector store size (points, end of episode)"),
        ("learnings_created", "learnings_created", "Raw learnings created"),
        ("known_rules_final", "known_rules_final", "Known rules at episode end"),
    ]

    lines = []
    lines.append("# 5x5 Persistent Maze Learning Benchmark - Computed Tables\n")
    lines.append(f"- Persistence OFF episodes: {len(rows_a)} (train {len(train_a)}, eval {len(eval_a)})")
    lines.append(f"- Persistence ON episodes: {len(rows_b)} (train {len(train_b)}, eval {len(eval_b)})\n")

    lines.append("## Per-episode (train episodes)\n")
    header = "| arm | ep | success | moves | optimal | excess | invalid | repeated | cells_visited | iterations | dur_s | tokens | retrieved | writes |"
    lines.append(header)
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(train_a + train_b, key=lambda x: (x["arm"], x["episode"])):
        lines.append(
            f"| {r['arm']} | {r['episode']} | {r['success']} | {r['moves_used']} | {r['optimal_moves']} | "
            f"{r['excess_moves']} | {r['invalid_moves']} | {r['repeated_moves']} | {r['cells_visited']} | "
            f"{r['iterations']} | {r['duration_s']:.0f} | {r['total_tokens']} | {r['retrieved_total']} | {r['writes_insert']}+{r['writes_merge']} |"
        )

    lines.append("\n## Aggregate comparison (train episodes)\n")
    lines.append("| metric | A-OFF mean | A-OFF median | A-OFF sd | B-ON mean | B-ON median | B-ON sd | abs diff | pct change |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    summary_table = {}
    for key, field, label in metrics:
        am, amed, asd = agg(train_a, field)
        bm, bmed, bsd = agg(train_b, field)
        diff = (bm - am) if (am is not None and bm is not None) else None
        pct = (100.0 * diff / am) if (am not in (None, 0) and diff is not None) else None
        summary_table[key] = {"a_mean": am, "b_mean": bm, "diff": diff, "pct": pct}
        lines.append(
            f"| {label} | {fmt(am)} | {fmt(amed)} | {fmt(asd)} | {fmt(bm)} | {fmt(bmed)} | {fmt(bsd)} | "
            f"{fmt(diff)} | {fmt(pct, 1)}% |"
        )

    (out_dir / "comparison.md").write_text("\n".join(lines), encoding="utf-8")

    with open(out_dir / "summary_stats.json", "w", encoding="utf-8") as f:
        json.dump({"metrics": summary_table,
                   "trends": {
                       "A_moves_slope": trend_slope(train_a, "moves_used"),
                       "B_moves_slope": trend_slope(train_b, "moves_used"),
                       "A_rules_slope": trend_slope(train_a, "known_rules_final"),
                       "B_rules_slope": trend_slope(train_b, "known_rules_final"),
                   },
                   "unseen_eval": {"A": eval_a, "B": eval_b}}, f, indent=2, default=str)

    # ------------------------- charts -------------------------
    charts = out_dir / "charts"
    colors = {"A-OFF": "#4472c4", "B-ON": "#ed7d31"}

    def series(rows, arm):
        return sorted([r for r in rows if r["arm"] == arm], key=lambda x: x["episode"])

    sa, sb = series(all_rows, "A-OFF"), series(all_rows, "B-ON")
    eps_idx = [r["episode"] for r in sa]

    def plot_metric(ax, key, title, ylabel, include_optimal=False):
        ax.plot([r["episode"] for r in sa], [r[key] for r in sa], marker="o", label="A - Persistence OFF", color=colors["A-OFF"])
        ax.plot([r["episode"] for r in sb], [r[key] for r in sb], marker="s", label="B - Persistence ON", color=colors["B-ON"])
        if include_optimal:
            ax.plot([r["episode"] for r in sa], [r["optimal_moves"] for r in sa], linestyle=":", color="gray", label="optimal moves")
        ax.set_title(title)
        ax.set_xlabel("Episode")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    plot_metric(axes[0][0], "moves_used", "Moves to Exit by Episode", "Moves", include_optimal=True)
    plot_metric(axes[0][1], "path_efficiency", "Path Efficiency (optimal / actual)", "Ratio")
    plot_metric(axes[1][0], "invalid_moves", "Invalid (Blocked) Moves", "Count")
    plot_metric(axes[1][1], "repeated_moves", "Repeated Moves (Revisits)", "Count")
    fig.tight_layout()
    fig.savefig(charts / "performance_trends.png", dpi=140)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    plot_metric(axes[0][0], "duration_s", "Episode Duration", "Seconds")
    plot_metric(axes[0][1], "llm_calls", "LLM Calls", "Calls")
    plot_metric(axes[1][0], "total_tokens", "Total Tokens", "Tokens")
    ax = axes[1][1]
    width = 0.35
    x = np.arange(len(sa))
    ax.bar(x - width / 2, [r["prompt_tokens"] for r in sa], width, label="A prompt", color=colors["A-OFF"], alpha=0.6)
    ax.bar(x + width / 2, [r["prompt_tokens"] for r in sb], width, label="B prompt", color=colors["B-ON"], alpha=0.6)
    ax.bar(x - width / 2, [r["completion_tokens"] for r in sa], width, bottom=[r["prompt_tokens"] for r in sa], label="A completion", color=colors["A-OFF"])
    ax.bar(x + width / 2, [r["completion_tokens"] for r in sb], width, bottom=[r["prompt_tokens"] for r in sb], label="B completion", color=colors["B-ON"])
    ax.set_xticks(x, [str(r["episode"]) for r in sa])
    ax.set_title("Token Usage (prompt + completion)")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Tokens")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(charts / "resource_usage.png", dpi=140)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    axes[0].plot([r["episode"] for r in sb], [r["retrieved_total"] for r in sb], marker="s", color=colors["B-ON"], label="B retrieved")
    axes[0].plot([r["episode"] for r in sa], [r["retrieved_total"] for r in sa], marker="o", color=colors["A-OFF"], label="A retrieved")
    axes[0].set_title("Memories Retrieved per Episode")
    axes[0].set_xlabel("Episode")
    axes[0].set_ylabel("Count")
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8)

    axes[1].plot([r["episode"] for r in sb], [r["writes_insert"] + r["writes_merge"] for r in sb], marker="s", color=colors["B-ON"], label="B writes")
    axes[1].plot([r["episode"] for r in sa], [r["writes_insert"] + r["writes_merge"] for r in sa], marker="o", color=colors["A-OFF"], label="A writes")
    axes[1].set_title("Memory Writes per Episode")
    axes[1].set_xlabel("Episode")
    axes[1].set_ylabel("Count")
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8)

    axes[2].plot([r["episode"] for r in sb], [r["points_after"] for r in sb], marker="s", color=colors["B-ON"], label="B store")
    axes[2].plot([r["episode"] for r in sa], [r["points_after"] for r in sa], marker="o", color=colors["A-OFF"], label="A store")
    axes[2].set_title("Vector Store Size (end of episode)")
    axes[2].set_xlabel("Episode")
    axes[2].set_ylabel("Points")
    axes[2].grid(alpha=0.3)
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(charts / "memory_activity.png", dpi=140)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    labels = ["Success rate", "Path efficiency", "Exploration eff."]
    a_vals = [agg(train_a, "success")[0] or 0, agg(train_a, "path_efficiency")[0] or 0, agg(train_a, "exploration_efficiency")[0] or 0]
    b_vals = [agg(train_b, "success")[0] or 0, agg(train_b, "path_efficiency")[0] or 0, agg(train_b, "exploration_efficiency")[0] or 0]
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, a_vals, width, label="A - Persistence OFF", color=colors["A-OFF"])
    ax.bar(x + width / 2, b_vals, width, label="B - Persistence ON", color=colors["B-ON"])
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.1)
    ax.set_title("Aggregate Quality Metrics (train episodes)")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(charts / "quality_comparison.png", dpi=140)

    if eval_a or eval_b:
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        names = [f"A eval", "B eval"]
        vals = [[eval_a[0]["success"] if eval_a else None, eval_b[0]["success"] if eval_b else None],
                [eval_a[0]["moves_used"] if eval_a else None, eval_b[0]["moves_used"] if eval_b else None],
                [eval_a[0]["duration_s"] if eval_a else None, eval_b[0]["duration_s"] if eval_b else None]]
        titles = ["Unseen 5x5 - Success", "Unseen 5x5 - Moves", "Unseen 5x5 - Duration (s)"]
        for ax, v, t in zip(axes, vals, titles):
            ax.bar(names, [0 if vv is None else vv for vv in v], color=[colors["A-OFF"], colors["B-ON"]])
            ax.set_title(t)
            ax.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        fig.savefig(charts / "unseen_eval.png", dpi=140)

    print(f"wrote {out_dir / 'comparison.md'}, episode_metrics.csv, summary_stats.json, charts/")
    print("A train episodes:", len(train_a), "| B train episodes:", len(train_b),
          "| A eval:", len(eval_a), "| B eval:", len(eval_b))


if __name__ == "__main__":
    main()
