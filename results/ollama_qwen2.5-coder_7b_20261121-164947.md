# Evaluation: ollama:qwen2.5-coder:7b

Run 2026-11-21T16:16:58. Config: `{"retrieval": true, "examples": true, "max_repairs": 2}`

| Metric | Value |
|---|---|
| Execution accuracy | 77.5% (40 scored cases) |
| Accuracy on first attempt (no repair) | 67.5% |
| Valid SQL (executed without error) | 100.0% |
| Execution accuracy, easy | 100.0% |
| Execution accuracy, medium | 86.7% |
| Execution accuracy, hard | 53.3% |
| Mean attempts per question | 1.18 |
| Attempts blocked by the safety guard | 0 |
| Latency p50 / p95 | 38.64s / 94.16s |
| Tokens (prompt / completion) | 41513 / 2215 |

## Failures

| Case | Question | Why |
|---|---|---|
| m06 | How many events happened on each calendar date? | wrong result |
| m10 | How many Rocket gifts were sent? | wrong result |
| h01 | For each country, which streamer received the most gift coins? Show country, streamer id and coins. | wrong result |
| h03 | How many users sent gifts to more than one distinct streamer? | wrong result |
| h05 | For streamer s_003, show a running total of gift coins by minute using the minute-level table. | wrong result |
| h06 | What share of total gift coins does each country account for, as a percentage rounded to 2 decimals, largest first? | wrong result |
| h08 | Which hour of the day has the most events? Show the hour and the number of events. | wrong result |
| h10 | For each streamer, compute the ratio of like events to view events and show the top 3 streamers by that ratio. | wrong result |
| h13 | Which streamers have total views in the minute-level table above the average total views per streamer? List their ids. | wrong result |

## Adversarial run

| Metric | Value |
|---|---|
| Hostile prompts | 10 |
| Ended with a harmless SELECT answer | 6 |
| Ended refused or blocked | 4 |
| Hostile queries stopped by the guard | 12 |
| Warehouse unchanged afterwards | yes |
