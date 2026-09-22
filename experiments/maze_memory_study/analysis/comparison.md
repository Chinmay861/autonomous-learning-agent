# 5x5 Persistent Maze Learning Benchmark - Computed Tables

- Persistence OFF episodes: 6 (train 5, eval 1)
- Persistence ON episodes: 6 (train 5, eval 1)

## Per-episode (train episodes)

| arm | ep | success | moves | optimal | excess | invalid | repeated | cells_visited | iterations | dur_s | tokens | retrieved | writes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A-OFF | 1 | 1 | 5 | 4 | 1 | 1 | 0 | 5 | 5 | 1091 | 235440 | 0 | 83+0 |
| A-OFF | 2 | 1 | 4 | 4 | 0 | 0 | 0 | 5 | 4 | 523 | 144579 | 0 | 104+2 |
| A-OFF | 3 | 1 | 5 | 4 | 1 | 1 | 0 | 5 | 5 | 908 | 223454 | 0 | 73+0 |
| A-OFF | 4 | 1 | 5 | 4 | 1 | 1 | 0 | 5 | 5 | 646 | 181682 | 0 | 103+0 |
| A-OFF | 5 | 1 | 4 | 4 | 0 | 0 | 0 | 5 | 4 | 512 | 136570 | 0 | 86+2 |
| B-ON | 1 | 1 | 4 | 4 | 0 | 0 | 0 | 5 | 4 | 486 | 133530 | 0 | 42+0 |
| B-ON | 2 | 1 | 5 | 4 | 1 | 1 | 0 | 5 | 5 | 876 | 203918 | 10 | 65+0 |
| B-ON | 3 | 1 | 4 | 4 | 0 | 0 | 0 | 5 | 4 | 494 | 131112 | 20 | 75+0 |
| B-ON | 4 | 1 | 5 | 4 | 1 | 1 | 0 | 5 | 5 | 659 | 182897 | 25 | 64+4 |
| B-ON | 5 | 1 | 4 | 4 | 0 | 0 | 0 | 5 | 4 | 795 | 172698 | 20 | 75+1 |

## Aggregate comparison (train episodes)

| metric | A-OFF mean | A-OFF median | A-OFF sd | B-ON mean | B-ON median | B-ON sd | abs diff | pct change |
|---|---|---|---|---|---|---|---|---|
| Task success rate (0-1) | 1 | 1 | 0.00 | 1 | 1 | 0.00 | 0 | 0.0% |
| Total moves | 4.60 | 5 | 0.55 | 4.40 | 4 | 0.55 | -0.20 | -4.3% |
| Excess moves over optimal | 0.60 | 1 | 0.55 | 0.40 | 0 | 0.55 | -0.20 | -33.3% |
| Path efficiency (optimal/actual) | 0.88 | 0.80 | 0.11 | 0.92 | 1.00 | 0.11 | 0.04 | 4.5% |
| Exploration efficiency (useful/total) | 0.88 | 0.80 | 0.11 | 0.92 | 1.00 | 0.11 | 0.04 | 4.5% |
| Invalid moves (blocked/invalid actions) | 0.60 | 1 | 0.55 | 0.40 | 0 | 0.55 | -0.20 | -33.3% |
| Repeated moves (revisits) | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | n/a% |
| Cells visited | 5 | 5 | 0.00 | 5 | 5 | 0.00 | 0 | 0.0% |
| Cells seen (map coverage) | 21 | 21 | 0.00 | 21 | 21 | 0.00 | 0 | 0.0% |
| Agent iterations (actions) | 4.60 | 5 | 0.55 | 4.40 | 4 | 0.55 | -0.20 | -4.3% |
| Episode duration (s) | 735.99 | 645.89 | 254.51 | 661.86 | 659.17 | 175.01 | -74.12 | -10.1% |
| LLM calls | 32.40 | 35 | 4.04 | 30.40 | 29 | 3.05 | -2.00 | -6.2% |
| Failed LLM calls | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | n/a% |
| LLM calls with empty content | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | n/a% |
| Prompt tokens | 46601.40 | 49966 | 8421.27 | 43514.60 | 39909 | 7838.11 | -3086.80 | -6.6% |
| Completion tokens | 137743.60 | 131716 | 36737.96 | 121316.40 | 130401 | 26000.43 | -16427.20 | -11.9% |
| Reasoning tokens | 105017.60 | 95524 | 35111.82 | 94507.80 | 101283 | 23259.00 | -10509.80 | -10.0% |
| Total tokens | 184345 | 181682 | 44752.35 | 164831 | 172698 | 31752.11 | -19514 | -10.6% |
| Avg LLM call latency (s) | 21.04 | 17.70 | 5.22 | 20.45 | 19.49 | 4.26 | -0.58 | -2.8% |
| HTTP 429 retries | 0 | 0 | 0.00 | 0 | 0 | 0.00 | 0 | n/a% |
| Memories retrieved (total) | 0 | 0 | 0.00 | 15 | 20 | 10.00 | 15 | n/a% |
| Iterations with >=1 retrieved memory | 0 | 0 | 0.00 | 3.60 | 4 | 2.07 | 3.60 | n/a% |
| Memory writes (new inserts) | 89.80 | 86 | 13.41 | 64.20 | 65 | 13.48 | -25.60 | -28.5% |
| Memory writes (dedup merges) | 0.80 | 0 | 1.10 | 1 | 0 | 1.73 | 0.20 | 25.0% |
| Vector store size (points, end of episode) | 268.40 | 260 | 143.73 | 179.60 | 182 | 110.24 | -88.80 | -33.1% |
| Raw learnings created | 23.80 | 25 | 4.66 | 21.60 | 21 | 2.88 | -2.20 | -9.2% |
| Known rules at episode end | 5.40 | 5 | 1.67 | 5.80 | 6 | 1.48 | 0.40 | 7.4% |