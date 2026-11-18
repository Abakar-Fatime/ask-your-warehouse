"""Synthetic warehouse with the same schema the streaming-warehouse project produces.

Lets the agent, tests and evaluation run with no other setup. Deterministic for a given seed.
Two streamers (s_018, s_019) never receive gifts, so anti-join questions have a real answer.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd

GIFTS = [("g_rose", "Rose", 1), ("g_heart", "Heart", 5), ("g_panda", "Panda", 25),
         ("g_rocket", "Rocket", 250), ("g_lion", "Lion", 1000)]
COUNTRIES = ["SG", "MY", "ID", "TH", "VN", "PH"]
DEVICES = ["ios", "android", "web"]
TYPES = ["view", "like", "comment", "gift_sent", "follow"]
REASONS = ["missing_user_id", "future_timestamp", "bad_event_type", "negative_gift_value", "unparsable_timestamp"]


def build(out: str | Path, n_events: int = 20000, seed: int = 7) -> Path:
    out = Path(out)
    rng = np.random.default_rng(seed)
    n_streamers = 20
    streamers = [f"s_{i:03d}" for i in range(n_streamers)]

    etype = rng.choice(TYPES, n_events, p=[0.55, 0.25, 0.12, 0.05, 0.03])
    streamer = rng.choice(streamers, n_events, p=np.linspace(2.0, 0.6, n_streamers) / np.linspace(2.0, 0.6, n_streamers).sum())
    # streamers s_018 and s_019 never receive gifts
    is_gift = etype == "gift_sent"
    blocked = is_gift & np.isin(streamer, ["s_018", "s_019"])
    etype[blocked] = "like"
    is_gift = etype == "gift_sent"

    start = pd.Timestamp("2026-11-01 18:00:00")
    offsets = np.sort(rng.integers(0, 2 * 24 * 3600 * 1000 // 8, n_events))  # ~6 hours spread over two evenings
    day_shift = (offsets % 2).astype("int64") * 24 * 3600 * 1000
    ts = start + pd.to_timedelta(np.sort(offsets + day_shift), unit="ms")

    gift_idx = rng.choice(len(GIFTS), n_events, p=[0.5, 0.25, 0.15, 0.07, 0.03])
    gift_id = np.where(is_gift, np.array([g[0] for g in GIFTS])[gift_idx], None)
    coins = np.where(is_gift, np.array([g[2] for g in GIFTS])[gift_idx], np.nan)
    watch = np.where(etype == "view", rng.integers(5, 600, n_events), np.nan)

    fact = pd.DataFrame({
        "event_id": [str(uuid.UUID(int=int(x))) for x in rng.integers(0, 2**62, n_events)],
        "event_type": etype,
        "event_time": ts,
        "user_id": [f"u_{i:05d}" for i in rng.integers(0, 2000, n_events)],
        "streamer_id": streamer,
        "room_id": ["r_" + s[2:] for s in streamer],
        "country": rng.choice(COUNTRIES, n_events),
        "device": rng.choice(DEVICES, n_events),
        "gift_id": gift_id,
        "gift_value_coins": pd.array(coins, dtype="Int64"),
        "watch_seconds": pd.array(watch, dtype="Int32"),
    })
    fact["event_date"] = fact["event_time"].dt.date

    minute = fact["event_time"].dt.floor("min")
    agg = (fact.assign(window_start=minute)
           .groupby(["window_start", "streamer_id"])
           .agg(views=("event_type", lambda s: int((s == "view").sum())),
                likes=("event_type", lambda s: int((s == "like").sum())),
                comments=("event_type", lambda s: int((s == "comment").sum())),
                gift_coins=("gift_value_coins", lambda s: int(s.fillna(0).sum())),
                active_users=("user_id", "nunique")).reset_index())
    agg["window_end"] = agg["window_start"] + pd.Timedelta(minutes=1)
    agg = agg[["window_start", "window_end", "streamer_id", "views", "likes", "comments", "gift_coins", "active_users"]]

    nq = 600
    quarantine = pd.DataFrame({
        "event_id": [str(uuid.UUID(int=int(x))) for x in rng.integers(0, 2**62, nq)],
        "event_type": rng.choice(TYPES + ["teleport"], nq),
        "event_ts": rng.choice(["not-a-timestamp", "2999-01-01T00:00:00.000Z", "2026-11-01T19:00:00.000Z"], nq),
        "user_id": rng.choice([None, "u_00001", "u_00002"], nq),
        "streamer_id": rng.choice(streamers, nq),
        "gift_value_coins": pd.array(rng.integers(-50, 5, nq), dtype="Int64"),
        "dq_reason": rng.choice(REASONS, nq, p=[0.25, 0.2, 0.2, 0.2, 0.15]),
    })

    out.mkdir(parents=True, exist_ok=True)
    fact.to_parquet(out / "fact_live_events", partition_cols=["event_date"], index=False)
    for name, df in {"agg_streamer_minute": agg, "quarantine": quarantine,
                     "dim_streamer": pd.DataFrame({"streamer_id": streamers, "streamer_name": [f"Streamer {s[2:]}" for s in streamers]}),
                     "dim_gift": pd.DataFrame(GIFTS, columns=["gift_id", "gift_name", "coin_value"]),
                     "dim_country": pd.DataFrame({"country": COUNTRIES}),
                     "dim_device": pd.DataFrame({"device": DEVICES})}.items():
        (out / name).mkdir(exist_ok=True)
        df.to_parquet(out / name / "part-00000.parquet", index=False)
    return out
