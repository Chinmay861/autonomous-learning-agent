# Persistent Agentic Memory — Controlled Comparative Study

**Task:** Persistent Maze Learning Benchmark (5×5 phase)
**Configurations:** A — Persistence OFF (retrieval disabled, learning/storage still on) · B — Persistence ON (retrieval enabled)
**Model:** `deepseek-v4.1-flash` via OpenCode Go (`https://opencode.ai/zen/go/v1`), `reasoning_effort=max` for all agent decision calls
**Date:** 2026‑09‑20 · **Runs:** 6 episodes per arm (5 training + 1 unseen evaluation), sequential within each arm, both arms in parallel on identical mazes
**Status:** Complete — 6/6 episodes succeeded in both arms

> **How to read this report.** Every section separates **OBSERVED** (raw instrumented measurements), **DERIVED** (computed statistics, percentages, tests), and **INTERPRETATION** (explanation, inference, judgement). Nothing here is fabricated; metrics that could not be measured reliably are explicitly marked **UNAVAILABLE** with reasons.

---

## 1. Executive Summary

**OBSERVED.** Both configurations solved 100% of episodes (5/5 training and the unseen evaluation) on the 5×5 maze set, with near-optimal paths (mean 4.4–4.6 moves over an optimal 4; 0 revisits). Memory ON retrieved 10–25 stored memory items per episode (75 total; 26 retrieval calls), and the vector store grew to 406 points by the end of Experiment B (554 in A). No failed LLM calls, no HTTP 429s, no empty responses in the final run.

**DERIVED.** Paired comparisons (same maze seeds, n = 5 episodes) show Memory ON trending toward slightly better efficiency without statistical significance: moves −0.20 (p = 0.62), path efficiency +0.04 (p = 0.62), invalid moves −0.20 (p = 0.62), duration −74 s / −10.1% (p = 0.72), total tokens −19,514 / −10.6% (p = 0.59), LLM calls −2.0 (p = 0.51). No within-arm learning trend (moves slope ≈ 0 in both arms). On the single unseen maze, B solved it in the optimal 4 moves with 0 invalid moves; A took 5 moves with 1 invalid move.

**INTERPRETATION.** The 5×5 phase exhibits a **ceiling effect**: both the OFF and ON agents solve every maze in 4–5 moves, so there is almost no headroom for memory to demonstrate benefit. The observed direction of every efficiency metric favors memory ON, but with n = 5 and effect sizes well inside run-to-run noise, **no practically or statistically meaningful performance difference can be attributed to persistent memory** in this phase. The study also uncovered that persistent memory was **non-functional in stock code** (two independent response-shape defects, §4.3); after harness-side repair, retrieval demonstrably occurred and its content was surfaced to the planner, yet the agent's behavior was already near-optimal, so the marginal value was not measurable.

---

## 2. Experimental Objective

**OBSERVED (specification).** Determine how persistent agentic memory affects task performance, efficiency, consistency, learning, and resource usage by running the *same* agentic task under two configurations:

- **A — Memory OFF:** no retrieval of prior knowledge; the agent solves each maze using only the current episode. Learning/storage remain active.
- **B — Memory ON:** the agent retrieves, and may use, knowledge from previous episodes; learning/storage remain active.

**Primary research question.** Does persistent access to accumulated experience enable an agent to improve its ability to solve previously **unseen** maze environments compared with an otherwise equivalent agent that cannot retrieve past experience?

---

## 3. System / Agent Architecture

**OBSERVED.** The host system is `autonomous-learning-agent` (FastAPI + async orchestrator). Each agent iteration executes:

1. **Observe** — read the maze environment state.
2. **Retrieve** (B only) — embed `Task + Environment state`, search the vector store (Qdrant, in-memory, cosine), top-k = 5, min similarity = 0.65.
3. **Plan** — LLM selects the next action (structured JSON, move direction).
4. **Act** — environment applies the move.
5. **Evaluate** — LLM scores the outcome.
6. **Extract learning** — LLM writes learning records (always, both arms).
7. **Rule discovery / strategy update** — LLM, conditionally per iteration.
8. **End of episode:** **synthesis** — LLM condenses raw learnings into reusable units, which are embedded and written to the vector store (always, both arms).

**Environment (implemented for this benchmark).** A deterministic `MazeEnvironment` (5×5/6×6/7×7 capable) with `S`, `E`, `.`, `#`, `K`, `D`, `T`; partial observability (agent sees its cell plus the surrounding 3×3; unseen cells show `?`); key-before-door rule; trap penalty of +5 moves. The 5×5 phase intentionally contains **no K/D/T** (per benchmark phase 1: basic navigation, walls, dead ends, exploration), with a 30-move budget. All 18 study mazes were validated solvable and their optimal paths pre-computed.

**Memory pipeline.** In-process Qdrant (`:memory:`), one store per experiment; retrieval ON/OFF is the only experimental variable. Embeddings: `all-MiniLM-L6-v2` (384-d).

---

## 4. Experimental Setup and Controlled Variables

### 4.1 Fixed variables (identical in A and B)

| Variable | Value |
|---|---|
| Model / endpoint | `deepseek-v4.1-flash` · `https://opencode.ai/zen/go/v1` |
| Reasoning effort (agent calls) | `max` |
| Temperature | 0.7 |
| Task description / system prompts / tools | identical |
| Environment code + maze seeds | identical (train 1001–1005; unseen eval 9001) |
| Move budget | 30 moves per episode |
| top_k / min_similarity | 5 / 0.65 |
| Snapshot / synthesis interval | 20 / end-of-episode (100) |
| Learning + storage | **always ON in both arms** |
| Instrumentation | identical harness, applied to both arms |
| Run order | 5 training episodes, then 1 unseen evaluation episode, sequential |

### 4.2 The single controlled difference

`use_persistent_learning` = `False` (A) vs `True` (B), which gates **only** memory retrieval. Storage/synthesis runs identically in both arms.

### 4.3 Defects discovered in the stock memory implementation (documented, identical repairs in both arms)

These were discovered while preparing the study and are material to interpreting any persistent-memory result in this codebase. All repairs are harness-side and applied **identically to both arms**; no run in either arm used unrepaired code.

1. **Memory was never written (write path broken).** The synthesis system prompt requests `{"synthesized_learnings": [...]}` (`backend/app/agents/prompts.py:247-249`), but the parser accepts only a bare list or the key `"units"` (`backend/app/agents/synthesis.py:60`). Result: synthesis succeeded (11 successful calls, 1.4k–16k characters of content) yet **0 units were parsed, 0 embeddings computed, 0 vector writes**. Evidence: `results/maze5_A_attempt2/` and `maze5_B_attempt2/` (0 writes, store size 0). Repair: normalize the synthesis response shape before parsing.
2. **Retrieved memories were never surfaced to the planner (read path broken).** The planner formats memories as `m['similarity']` / `m['learning']` (`backend/app/agents/experiment_planner.py:104-108`), but retrieval returns `{id, score, payload}` (`qdrant_store.search` → `retriever`). Every retrieved memory therefore rendered as `[0.00] ?`. Repair: flatten `score`/`knowledge` into the keys the planner reads (ON arm only).
3. **Synthesis at `reasoning_effort=max` fails upstream.** Batches generated 20k–41k reasoning tokens and the gateway returned HTTP 500 (two failures in A, one in B, all writes lost). Repair: synthesis batches run at `reasoning_effort=low`; all agent decision calls stay at `max` (documented deviation, identical in both arms).
4. **Exhausted 429 retries can return `None`** (`backend/app/models/llm_provider.py:161-183`), producing `'NoneType' object is not subscriptable` in evaluator/extractor/synthesis (observed on Groq in a preliminary run). Repair: retry HTTP 5xx at the harness boundary; final runs had 0 failures.
5. **`source_iterations` list-vs-int merge crash** (`backend/app/memory/memory_manager.py:66`) — latent; repaired by coercion.
6. **Environment fidelity.** The pre-existing grid environment did not implement K/D/T/`?` semantics; the maze environment used here was implemented for the benchmark. The 5×5 phase contains no K/D/T by design, so trap/key/door metrics are **not applicable** in this report.

### 4.4 Timeline / run integrity

- Attempt 1 (effort=max synthesis): **aborted** after EP01 in both arms (500s, no writes).
- Attempt 2 (synthesis effort fixed): **aborted** after EP01 in both arms (units never parsed — defect #1).
- **Attempt 3 (final): both experiments complete, 6/6 episodes each**, no failed calls, no 429s, no empty content. Archived attempts retained as evidence.

---

## 5. Memory OFF Results (Experiment A)

**OBSERVED — per-episode (training):**

| Ep | Success | Moves | Optimal | Excess | Invalid | Repeats | Iters | Duration | Tokens | Retrieved | Mem writes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | 5 | 4 | 1 | 1 | 0 | 5 | 1091 s | 235,440 | 0 | 83 |
| 2 | yes | 4 | 4 | 0 | 0 | 0 | 4 | 523 s | 144,579 | 0 | 106 |
| 3 | yes | 5 | 4 | 1 | 1 | 0 | 5 | 908 s | 223,454 | 0 | 73 |
| 4 | yes | 5 | 4 | 1 | 1 | 0 | 5 | 646 s | 181,682 | 0 | 103 |
| 5 | yes | 4 | 4 | 0 | 0 | 0 | 4 | 512 s | 136,570 | 0 | 88 |

**OBSERVED — unseen 5×5 evaluation:** success, 5 moves (optimal 4), 1 invalid move, 5 iterations, 751 s, 209,366 tokens, 0 retrieved, 105 writes.

**DERIVED (train, n=5):** success rate 100%; moves mean 4.60 / median 5 / sd 0.55; path efficiency mean 0.88; invalid moves mean 0.60; repeated moves 0; duration mean 736 s (sd 254.5); tokens mean 184,345 (sd 44,752); LLM calls mean 32.4; store size end 554 points; notional API cost (5 episodes) $0.448.

**INTERPRETATION.** A roofed baseline: every maze solved in the minimum or near-minimum number of moves, no revisits, minimal blocking. Resource usage is dominated by LLM latency/reasoning (each iteration ≈ 4.9 calls × ~21 s), not by navigation inefficiency.

---

## 6. Memory ON Results (Experiment B)

**OBSERVED — per-episode (training):**

| Ep | Success | Moves | Optimal | Excess | Invalid | Repeats | Iters | Duration | Tokens | Retrieved | Mem writes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | 4 | 4 | 0 | 0 | 0 | 4 | 486 s | 133,530 | 0 | 42 |
| 2 | yes | 5 | 4 | 1 | 1 | 0 | 5 | 876 s | 203,918 | 10 | 65 |
| 3 | yes | 4 | 4 | 0 | 0 | 0 | 4 | 494 s | 131,112 | 20 | 75 |
| 4 | yes | 5 | 4 | 1 | 1 | 0 | 5 | 659 s | 182,897 | 25 | 68 |
| 5 | yes | 4 | 4 | 0 | 0 | 0 | 4 | 795 s | 172,698 | 20 | 76 |

**OBSERVED — unseen 5×5 evaluation:** success, **4 moves (optimal)**, **0 invalid moves**, 4 iterations, 847 s, 169,623 tokens, 20 retrieved, 85 writes.

**DERIVED (train, n=5):** success rate 100%; moves mean 4.40 / median 4 / sd 0.55; path efficiency mean 0.92; invalid moves mean 0.40; repeated 0; duration mean 662 s (sd 175.0); tokens mean 164,831 (sd 31,752); LLM calls mean 30.4; store size end 406 points; notional API cost $0.397.

**INTERPRETATION.** The ON agent behaves like the OFF agent on this maze class, while carrying an active retrieval pipeline. Its unseen-eval run is the single instance with a visible edge (optimal path, no blocking), consistent with the general direction of the small train-episode advantages — but a single episode cannot support a generalization claim.

---

## 7. Comparative Metrics Table

**DERIVED — training episodes (paired by identical maze seed, n = 5).** *abs diff and % are B−A / relative to A.* Statistical tests: paired t-test and Wilcoxon signed-rank (low power; exact p values approach 1.0 due to tiny sample and periodic data).

| Metric | A OFF mean | A median | A sd | B ON mean | B median | B sd | Δ abs | Δ % | paired p |
|---|---|---|---|---|---|---|---|---|---|
| Success rate | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 0.00 | 0 | 0% | n/a |
| Total moves | 4.60 | 5 | 0.55 | 4.40 | 4 | 0.55 | −0.20 | −4.3% | 0.621 |
| Excess over optimal | 0.60 | 1 | 0.55 | 0.40 | 0 | 0.55 | −0.20 | −33.3% | 0.621 |
| Path efficiency | 0.88 | 0.80 | 0.11 | 0.92 | 1.00 | 0.11 | +0.04 | +4.5% | 0.621 |
| Exploration efficiency | 0.88 | 0.80 | 0.11 | 0.92 | 1.00 | 0.11 | +0.04 | +4.5% | 0.621 |
| Invalid moves | 0.60 | 1 | 0.55 | 0.40 | 0 | 0.55 | −0.20 | −33.3% | 0.621 |
| Repeated moves | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | n/a | n/a |
| Iterations (actions) | 4.60 | 5 | 0.55 | 4.40 | 4 | 0.55 | −0.20 | −4.3% | 0.621 |
| Duration (s) | 736.0 | 645.9 | 254.5 | 661.9 | 659.2 | 175.0 | −74.1 | −10.1% | 0.715 |
| LLM calls | 32.4 | 35 | 4.04 | 30.4 | 29 | 3.05 | −2.0 | −6.2% | 0.508 |
| Failed LLM calls | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | — | n/a |
| Empty-content calls | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | — | n/a |
| Prompt tokens | 46,601 | 49,966 | 8,421 | 43,515 | 39,909 | 7,838 | −3,087 | −6.6% | 0.619 |
| Completion tokens | 137,744 | 131,716 | 36,738 | 121,316 | 130,401 | 26,000 | −16,427 | −11.9% | 0.584 |
| Reasoning tokens | 105,018 | 95,524 | 35,112 | 94,508 | 101,283 | 23,259 | −10,510 | −10.0% | — |
| Total tokens | 184,345 | 181,682 | 44,752 | 164,831 | 172,698 | 31,752 | −19,514 | −10.6% | 0.587 |
| Avg LLM latency (s) | 21.04 | 17.70 | 5.22 | 20.45 | 19.49 | 4.26 | −0.58 | −2.8% | 0.889 |
| HTTP 429 retries | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | — | n/a |
| Memories retrieved | 0 | 0 | 0.00 | 15.0 | 20 | 10.0 | +15.0 | — | — |
| Iterations w/ ≥1 memory | 0 | 0 | 0.00 | 3.60 | 4 | 2.07 | +3.60 | — | — |
| Memory inserts | 89.8 | 86 | 13.4 | 64.2 | 65 | 13.5 | −25.6 | −28.5% | — |
| Memory merges (dedup) | 0.8 | 0 | 1.10 | 1.0 | 0 | 1.73 | +0.2 | +25% | — |
| Vector store size (end) | 268.4 | 260 | 143.7 | 179.6 | 182 | 110.2 | −88.8 | −33.1% | — |
| Raw learnings created | 23.8 | 25 | 4.66 | 21.6 | 21 | 2.88 | −2.2 | −9.2% | — |
| Known rules (end) | 5.4 | 5 | 1.67 | 5.8 | 6 | 1.48 | +0.4 | +7.4% | — |

**INTERPRETATION.** Every directional quality metric favors ON (fewer moves, fewer invalid moves, higher efficiency, less time, fewer tokens), yet no difference approaches significance. The **memory-write counts favor OFF** (89.8 vs 64.2 inserts) — an unexpected side effect discussed in §10.

---

## 8. Run-by-Run Analysis

**OBSERVED / DERIVED.**

| Episode (same maze seed both arms) | A moves / duration / tokens | B moves / duration / tokens | B retrieved | Notes |
|---|---|---|---|---|
| EP1 (seed 1001) | 5 / 1091 s / 235k | 4 / 486 s / 134k | 0 | B optimal, fastest episode of either arm; store empty so no retrieval |
| EP2 (seed 1002) | 4 / 523 s / 145k | 5 / 876 s / 204k | 10 | A optimal; retrieval active but B took an extra move |
| EP3 (seed 1003) | 5 / 908 s / 223k | 4 / 494 s / 131k | 20 | B optimal and 2× faster than A |
| EP4 (seed 1004) | 5 / 646 s / 182k | 5 / 659 s / 183k | 25 | Near-identical runs |
| EP5 (seed 1005) | 4 / 512 s / 137k | 4 / 795 s / 173k | 20 | Both optimal; A faster |
| EP6 (unseen 9001) | 5 / 751 s / 209k | 4 / 847 s / 169k | 20 | B optimal with 0 blocks; A 1 block |

**INTERPRETATION.** The per-episode pattern alternates (B better on EP1/EP3/EP6, A better on EP2/EP5, tied on EP4). This is the signature of run-to-run LLM variance (temperature 0.7) dominating a ceiling-limited task, not of a systematic memory effect. Where B "wins", the win is 1 move out of an optimal 4 (`EP1`, `EP3`, unseen). Where A wins, the win is time in a low-variance comparison (`EP5`).

---

## 9. Learning / Improvement Trend Analysis

**DERIVED.**
- Moves slope per episode: A = −0.10, B = −0.00 (i.e., flat; the task is solved at near-optimal from episode 1).
- Early (EP1–2) vs late (EP4–5) moves: A 5,4 → 5,4; B 4,5 → 5,4. No improvement in either arm.
- Duration slope: A = −104 s/episode (driven by an outlier EP1), B = +40 s/episode (noise).
- Token slope: A = −16,064, B = +5,732 (noise).
- Retrieval activity (B): 0 → 10 → 20 → 25 → 20 items per episode, i.e., retrieval became active once the store existed and remained high; 3.6 of 4.4 iterations per episode contained ≥1 retrieved memory.

**INTERPRETATION.** There is **no measurable learning curve** in either arm on 5×5 mazes, in moves or resources. The benchmark’s phase‑1 task is too easy for a `max`-effort reasoning model: both arms find (near-)optimal paths immediately, leaving no headroom for accumulation or transfer to manifest. The hypothesis that memory improves *later* episodes cannot be supported or rejected by this data; the experimental design must move to the 6×6/7×7 phases (key/door/trap, longer paths) for a fair test.

---

## 10. Impact of Persistent Agentic Memory

**OBSERVED.**
- Retrieval occurred in Experiment B: 26 retrieval calls across the experiment, 95 retrieval slots, **11 unique memory IDs** in total; similarity of retrieved items 0.663–0.817 (mean 0.724). Retrieval latency 15.1 s total; embedding work 3.8 min total (~6% of LLM time in both arms — nearly identical because both arms embed for writes).
- Memory content *was* surfaced to the planner in the ON arm (after the §4.3 repair); B’s planner prompts consequently contained real memory text, yet prompt tokens did **not** increase (B 43.5k vs A 46.6k, n.s.).
- Storage: A wrote more units (89.8 inserts/episode) than B (64.2), and A’s store ended larger (554 vs 406 points). Dedup merges were rare in both arms (9 in B total).

**DERIVED.** All paired deltas favor ON but none are significant (§7). Consistency: B’s duration sd was lower (175 s vs 254 s) and token sd lower (31.8k vs 44.8k); moves sd identical (0.55).

**INTERPRETATION.**
- *What changed when memory was enabled:* the agent performed and surfaced real retrieval in ~80% of iterations, but its decisions and outcomes were statistically indistinguishable from OFF. Memory added no measurable overhead in tokens or latency; the only cost is retrieval/embedding compute (~6% of LLM time, present in both arms for writes anyway).
- *Whether memory reduced repeated work:* repeated moves were 0 in both arms; invalid moves were marginally lower in ON (0.40 vs 0.60, p = 0.62). Not demonstrable.
- *Negative effects:* the **lower write counts in ON** (89.8 → 64.2 inserts/episode) is an observed side effect of the treatment, not explained by retrieval per se; plausible mechanisms are (a) different action trajectories producing fewer synthesizable learnings, (b) run-to-run synthesis variance (synthesis ran at low effort; unit counts varied 1–20 per batch in both arms). This is a trade-off worth monitoring: *retrieval of previous knowledge may slightly reduce the volume of newly stored knowledge* — though with n = 5 this may also be noise.
- *Staleness/duplication risk:* only 11 unique IDs were ever retrieved from a 400+ point store. The retrieval query repeats the same task text and a near-identical state string, so the top-5 is dominated by the same few generic lessons; 95 retrieval slots mapped to 11 items. That is a real, observed redundancy pattern (the same knowledge re-injected every iteration), and dedup merges (9) were too rare to prune it.
- *Knowledge reuse:* availability is measured, **influence is not isolable** in this design; mark as **UNAVAILABLE** (no counterfactual agent without surfaced memories was run, and the ceiling effect prevents behavioral attribution).

---

## 11. Benefits and Trade-offs

**OBSERVED / DERIVED.**

| Aspect | Result |
|---|---|
| Task success | 100% both arms — no benefit measurable |
| Moves / efficiency | Directional benefit for ON (−0.2 moves, +4.5% path efficiency), n.s. |
| Unseen maze | ON optimal (4/4 moves, 0 blocks) vs OFF 5 moves, 1 block — n = 1 |
| Latency | ON −10.1% mean duration, n.s.; ON more consistent (sd 175 s vs 254 s) |
| Tokens | ON −10.6% mean tokens, n.s.; ON lower variance |
| Memory overhead | Retrieval 15 s total; embeddings ~4 min per arm (~6% of LLM time); no prompt-token inflation measured |
| Storage | OFF stored more units (89.8 vs 64.2 inserts/episode) — counterintuitive, likely variance-driven |
| Errors | 0 failed calls, 0 empty responses, 0 retries in the final runs (both arms) |
| Redundancy | 95 retrieval slots → 11 unique memories; repeated re-injection of the same items |

**INTERPRETATION.** On this task and scale, persistent memory behaved as a *risk-free but benefit-neutral* channel: correctness, latency, and token use were statistically unchanged; the small directional gains and the single optimal unseen-eval run are encouraging but cannot be separated from noise. The main practical risks are **redundant retrieval** (few unique items dominate) and a possible **reduction in new knowledge production** when retrieval is active.

---

## 12. Limitations and Threats to Validity

1. **Sample size.** n = 5 training episodes per arm (plus one unseen eval). Only very large effects could reach significance; all observed effects are small and non-significant. Reported percentages should be read as descriptive.
2. **Ceiling effect.** 5×5 mazes are solved near-optimally by a max-effort reasoning model from episode 1 (100% success, ≤1 move over optimal). The benchmark cannot surface memory benefits in this phase; the 6×6/7×7 phases (keys, doors, traps, longer paths) were not run per the requested scope.
3. **Harness-side repairs.** The stock system could not write or surface memories (§4.3). Results describe a *repaired* pipeline; both arms were repaired identically, so the A/B contrast remains controlled, but the numbers do **not** describe stock behavior — stock behavior would show zero memory effect by construction.
4. **Synthesis effort.** Synthesis ran at `reasoning_effort=low` (all agent decisions at `max`) because max-effort synthesis caused upstream HTTP 500s and zero memory writes. Memory-unit quality/volume may be affected; identical in both arms.
5. **Run order / drift.** Episodes were sequential within each arm; API-side drift, machine load, and time-of-day differences could contribute to duration variance. The arms ran in parallel but not in lockstep episode-by-episode.
6. **Single unseen maze.** Generalization evidence rests on one 5×5 maze per arm.
7. **UNAVAILABLE metrics.** CPU/RAM consumption: not instrumented — unavailable. Trap activations / key–door behavior: not applicable in the 5×5 phase (no K/D/T by design; measured 0). Repeated-mistake rate: not estimable (0 revisits; invalid moves ≈ 0.5/episode). Knowledge-reuse *causal influence*: not isolable in this design. HTTP 429s/retries: 0 in the final run; the Groq 429→`None` defect was observed only in a preliminary attempt and is not part of the final measurements. API cost: token counts are exact; dollar figures are notional (subscription billing, not per-token).
8. **Instrumentation scope.** LLM token usage comes from provider `usage` fields; latency is wall-clock per call; “tool calls” are environment actions (one per iteration) plus internal LLM calls — there is no separate external tool invocation layer in this system.

---

## 13. Final Findings

1. **OBSERVED:** Persistent memory, once repaired, functioned correctly — retrieval occurred (75 items across 5 training episodes; 26 calls; 11 unique memories), storage grew (406 points in B), and no errors were recorded.
2. **OBSERVED:** Both configurations achieved 100% success with near-optimal paths; no failed calls, no retries, no empty outputs.
3. **DERIVED:** Every efficiency deltas favors ON (moves −4.3%, invalid moves −33%, duration −10.1%, tokens −10.6%, path efficiency +4.5%) but **none is statistically significant** (paired p = 0.51–0.89, n = 5).
4. **DERIVED:** No learning trend within either arm (moves slope ≈ 0); retrieval activity stabilized at 4–5 memories per iteration with only 11 unique items dominating the top-k.
5. **OBSERVED:** On the single unseen maze, ON found the optimal path with no invalid moves while OFF used one extra move and one invalid move — suggestive, not conclusive (n = 1).
6. **INTERPRETATION / PRIMARY ANSWER:** For the 5×5 phase of this benchmark and this model, **persistent agentic memory did not produce a measurable improvement** in success, moves, efficiency, latency, or token usage. The task has a ceiling, the sample is small, and the observed direction is weakly favorable. The decisive test of the primary research question requires the harder phases (6×6/7×7 with keys, doors, traps, and longer routes), where suboptimal first attempts actually occur.
7. **MATERIAL DISCOVERY:** In this codebase, persistent memory was **doubly non-functional in stock code** — the write path dropped all synthesized units (response-key mismatch) and the read path never surfaced retrieved content to the planner (payload-shape mismatch). Any prior “persistence ON” comparison in this project would have measured a no-op. Both defects are documented with file references in §4.3 for necessary production fixes.

---

## 14. Appendix — Raw Data and Artifacts

All artifacts are under `experiments/maze_memory_study/`.

| Artifact | Path |
|---|---|
| Per-episode metrics (CSV) | `analysis/episode_metrics.csv` |
| Computed comparison tables | `analysis/comparison.md` |
| Detailed stats JSON | `analysis/summary_stats.json` |
| Charts | `analysis/charts/*.png` |
| Experiment A summary | `results/maze5_A/study_summary.json` |
| Experiment B summary | `results/maze5_B/study_summary.json` |
| Per-episode metrics/events | `results/maze5_{A,B}/runs/EP*/metrics.json`, `events.jsonl` |
| LLM call log (tokens, latency, retries) | `results/maze5_{A,B}/llm_calls.jsonl` |
| HTTP log (status, retries) | `results/maze5_{A,B}/http_calls.jsonl` |
| Memory ops (retrieval, writes, normalizations) | `results/maze5_{A,B}/memory.jsonl` |
| Harness/runner logs | `results/maze5_{A,B}/harness.log` |
| Frozen protocol | `results/maze5_{A,B}/protocol.json` |
| Aborted attempts (defect evidence) | `results/maze5_{A,B}_attempt1/`, `..._attempt2/` |

**Charts.** `charts/performance_trends.png` (moves vs episode with optimal reference, path efficiency, invalid moves, repeats) · `charts/resource_usage.png` (duration, LLM calls, tokens, prompt/completion split) · `charts/memory_activity.png` (retrieved items, memory writes, vector-store growth) · `charts/quality_comparison.png` (aggregate success/efficiency) · `charts/unseen_eval.png` (unseen 5×5 outcomes).

**Raw per-episode data (training, both arms)** — see the table at the top of §5–§8 and `analysis/episode_metrics.csv` for all 27 columns including every memory and token metric used above.

**Notional cost** (DeepSeek V4.1 Flash off-peak rates, $0.15/M input, $0.60/M output; subscription billing applies in practice):
- Experiment A (5 training episodes): 233,007 input + 688,718 output tokens ≈ **$0.448**
- Experiment B (5 training episodes): 217,573 input + 606,582 output tokens ≈ **$0.397**

---

*This report contains only measurements produced by the instrumented harness on this machine. Where a metric could not be measured reliably it is marked UNAVAILABLE with the reason (§12.7). The controlled variable throughout was `use_persistent_learning` (retrieval) OFF vs ON; all other inputs, prompts, environment code, maze sequences, budgets, model parameters, and instrumentation were identical.*
