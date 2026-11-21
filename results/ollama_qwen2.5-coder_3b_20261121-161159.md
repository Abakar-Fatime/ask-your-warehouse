# Evaluation: ollama:qwen2.5-coder:3b

Run 2026-11-21T15:56:14. Config: `{"retrieval": true, "examples": true, "max_repairs": 2}`

| Metric | Value |
|---|---|
| Execution accuracy | 65.0% (40 scored cases) |
| Accuracy on first attempt (no repair) | 57.5% |
| Valid SQL (executed without error) | 95.0% |
| Execution accuracy, easy | 90.0% |
| Execution accuracy, medium | 73.3% |
| Execution accuracy, hard | 40.0% |
| Mean attempts per question | 1.18 |
| Attempts blocked by the safety guard | 0 |
| Latency p50 / p95 | 17.33s / 42.58s |
| Tokens (prompt / completion) | 42537 / 2445 |

## Failures

| Case | Question | Why |
|---|---|---|
| e03 | How many gift events were sent in total? | wrong result |
| m06 | How many events happened on each calendar date? | wrong result |
| m10 | How many Rocket gifts were sent? | wrong result |
| m13 | What is the average number of likes per streamer-minute in the minute-level table? | wrong result |
| m14 | What percentage of all events are likes? Round to one decimal place. | wrong result |
| h01 | For each country, which streamer received the most gift coins? Show country, streamer id and coins. | wrong result |
| h03 | How many users sent gifts to more than one distinct streamer? | wrong result |
| h04 | Which streamers received no gifts at all? List their ids. | wrong result |
| h06 | What share of total gift coins does each country account for, as a percentage rounded to 2 decimals, largest first? | The query failed with this error: Binder Error: Referenced column "country" not found in F |
| h08 | Which hour of the day has the most events? Show the hour and the number of events. | wrong result |
| h10 | For each streamer, compute the ratio of like events to view events and show the top 3 streamers by that ratio. | The query failed with this error: Binder Error: Values list "sv" does not have a column na |
| h11 | Which 5 streamer names earned the most coins from Rocket and Lion gifts combined? | wrong result |
| h13 | Which streamers have total views in the minute-level table above the average total views per streamer? List their ids. | wrong result |
| h15 | For each device, what share of its events are gifts? Show device and the percentage rounded to 2 decimals, highest first. | wrong result |

## Adversarial run

| Metric | Value |
|---|---|
| Hostile prompts | 10 |
| Ended with a harmless SELECT answer | 9 |
| Ended refused or blocked | 1 |
| Hostile queries stopped by the guard | 9 |
| Warehouse unchanged afterwards | yes |
