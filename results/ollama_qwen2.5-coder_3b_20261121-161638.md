# Evaluation: ollama:qwen2.5-coder:3b

Run 2026-11-21T16:12:00. Config: `{"retrieval": false, "examples": true, "max_repairs": 2}`

| Metric | Value |
|---|---|
| Execution accuracy | 72.5% (40 scored cases) |
| Accuracy on first attempt (no repair) | 70.0% |
| Valid SQL (executed without error) | 97.5% |
| Execution accuracy, easy | 90.0% |
| Execution accuracy, medium | 86.7% |
| Execution accuracy, hard | 46.7% |
| Mean attempts per question | 1.1 |
| Attempts blocked by the safety guard | 0 |
| Latency p50 / p95 | 5.26s / 17.98s |
| Tokens (prompt / completion) | 50817 / 1700 |

## Failures

| Case | Question | Why |
|---|---|---|
| e03 | How many gift events were sent in total? | wrong result |
| m06 | How many events happened on each calendar date? | wrong result |
| m10 | How many Rocket gifts were sent? | The query failed with this error: Binder Error: Referenced column "gift_name" not found in |
| h01 | For each country, which streamer received the most gift coins? Show country, streamer id and coins. | wrong result |
| h03 | How many users sent gifts to more than one distinct streamer? | wrong result |
| h06 | What share of total gift coins does each country account for, as a percentage rounded to 2 decimals, largest first? | wrong result |
| h08 | Which hour of the day has the most events? Show the hour and the number of events. | wrong result |
| h10 | For each streamer, compute the ratio of like events to view events and show the top 3 streamers by that ratio. | wrong result |
| h11 | Which 5 streamer names earned the most coins from Rocket and Lion gifts combined? | wrong result |
| h13 | Which streamers have total views in the minute-level table above the average total views per streamer? List their ids. | wrong result |
| h15 | For each device, what share of its events are gifts? Show device and the percentage rounded to 2 decimals, highest first. | wrong result |
