"""Telemetry aggregation and benchmark persistence over Memory Bank traces.

Computes runtime token usage, latency, 3-tier vs All-Ultra costs, and percentage
savings strictly from persisted `pipeline_state.trace` entries and `benchmarks`
documents without any hardcoded fallback percentages.
"""
from __future__ import annotations

import datetime
import statistics
import time
from typing import Any

from . import clients, config


def aggregate_run_costs(user_id: str) -> dict[str, Any]:
    """Aggregates token usage, latency, actual 3-tier cost, and All-Ultra baseline
    cost over `pipeline_state.trace` entries for a single `user_id`."""
    snap = clients.state_store().collection(config.COLL_STATE).document(user_id).get()
    if not snap.exists:
        return {
            "user_id": user_id,
            "found": False,
            "steps_count": 0,
            "total_latency_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "actual_cost_usd": 0.0,
            "all_ultra_cost_usd": 0.0,
            "savings_usd": 0.0,
            "savings_pct": None,
            "measured_at": None,
            "tier_steps": {"nano": 0, "super": 0, "ultra": 0},
            "steps": [],
            "trace": [],
        }

    doc = snap.to_dict()
    trace = doc.get("trace") or []
    total_latency_ms = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    cost_usd = 0.0
    all_ultra_cost_usd = 0.0
    latest_ts: str | None = None
    tier_steps = {"nano": 0, "super": 0, "ultra": 0}
    steps: list[dict[str, Any]] = []

    for idx, entry in enumerate(trace, start=1):
        lat = float(entry.get("latency_ms", 0.0) or 0.0)
        p_tok = int(entry.get("prompt_tokens", 0) or 0)
        c_tok = int(entry.get("completion_tokens", 0) or 0)
        c_usd = float(entry.get("cost_usd", 0.0) or 0.0)
        u_usd = float(entry.get("all_ultra_cost_usd", 0.0) or 0.0)
        total_latency_ms += lat
        prompt_tokens += p_tok
        completion_tokens += c_tok
        cost_usd += c_usd
        all_ultra_cost_usd += u_usd
        model_id = str(entry.get("model") or config.NEMOTRON_ULTRA_MODEL)
        m_low = model_id.lower()
        if "nano" in m_low:
            tier_steps["nano"] += 1
        elif "super" in m_low:
            tier_steps["super"] += 1
        else:
            tier_steps["ultra"] += 1
        evt_type = entry.get("type", "step")
        tool_name = entry.get("tool")
        steps.append(
            {
                "step": idx,
                "agent": entry.get("agent", "?"),
                "model": model_id,
                "event": f"{evt_type}:{tool_name}" if tool_name else evt_type,
                "latency_ms": round(lat, 1),
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "actual_cost_usd": round(c_usd, 6),
                "all_ultra_cost_usd": round(u_usd, 6),
            }
        )
        ts = entry.get("t")
        if ts and (latest_ts is None or str(ts) > latest_ts):
            latest_ts = str(ts)

    if not latest_ts and doc.get("updated"):
        latest_ts = str(doc.get("updated"))

    cost_usd = round(cost_usd, 6)
    all_ultra_cost_usd = round(all_ultra_cost_usd, 6)
    savings_usd = round(max(0.0, all_ultra_cost_usd - cost_usd), 6)
    savings_pct = (
        round((1.0 - (cost_usd / all_ultra_cost_usd)) * 100.0, 1)
        if all_ultra_cost_usd > 0
        else None
    )

    return {
        "user_id": user_id,
        "found": True,
        "stage": doc.get("stage", "UNKNOWN"),
        "steps_count": len(trace),
        "total_latency_ms": round(total_latency_ms, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_usd": cost_usd,
        "actual_cost_usd": cost_usd,
        "all_ultra_cost_usd": all_ultra_cost_usd,
        "savings_usd": savings_usd,
        "savings_pct": savings_pct,
        "measured_at": latest_ts,
        "tier_steps": tier_steps,
        "steps": steps,
        "trace": trace,
    }


def aggregate_all() -> dict[str, Any]:
    """Aggregates token usage, latency, and cost savings across all pipeline runs
    in `pipeline_state` that have non-zero token telemetry."""
    coll = clients.state_store().collection(config.COLL_STATE)
    runs: list[dict[str, Any]] = []
    for snap in coll.stream():
        agg = aggregate_run_costs(snap.id)
        if agg["all_ultra_cost_usd"] > 0 or agg["total_tokens"] > 0:
            runs.append(agg)

    runs.sort(key=lambda r: str(r.get("measured_at") or ""), reverse=True)
    n_runs = len(runs)
    total_prompt = sum(r["prompt_tokens"] for r in runs)
    total_completion = sum(r["completion_tokens"] for r in runs)
    total_cost = round(sum(r["cost_usd"] for r in runs), 6)
    total_ultra = round(sum(r["all_ultra_cost_usd"] for r in runs), 6)
    total_savings = round(max(0.0, total_ultra - total_cost), 6)
    savings_pct = (
        round((1.0 - (total_cost / total_ultra)) * 100.0, 1)
        if total_ultra > 0
        else None
    )
    latest_ts = runs[0]["measured_at"] if runs else None
    measured_date = latest_ts[:10] if latest_ts else "N/A"

    return {
        "runs_count": n_runs,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_usd": total_cost,
        "actual_cost_usd": total_cost,
        "total_all_ultra_cost_usd": total_ultra,
        "all_ultra_cost_usd": total_ultra,
        "total_savings_usd": total_savings,
        "mean_cost_per_run_usd": round(total_cost / n_runs, 6) if n_runs else 0.0,
        "mean_all_ultra_per_run_usd": round(total_ultra / n_runs, 6) if n_runs else 0.0,
        "savings_pct": savings_pct,
        "measured_at": latest_ts,
        "measured_date": measured_date,
        "summary_label": f"{n_runs} runs, measured {measured_date}" if n_runs else "0 runs measured",
        "runs": runs,
    }


def run_and_persist_tier_benchmark(
    runs_per_tier: int = 5,
    prompt: str = (
        "Patient carries CYP2C19 *2/*2 (rs4244285 homozygous A/A). "
        "In 2 concise sentences, state the CPIC Level-A metabolizer phenotype for clopidogrel "
        "and why alternative P2Y12 therapy is discussed."
    ),
    enable_thinking: bool = False,
) -> dict[str, Any]:
    """Runs the 3-tier Nebius Token Factory benchmark `runs_per_tier` times per model
    tier (counting each LLM call against the daily quota), computes median latency
    and mean token cost, and persists the result to the `benchmarks` collection."""
    runs_per_tier = max(1, min(int(runs_per_tier), 10))
    tiers = [
        ("Tier 1 — Nano 30B (MoE A3B)", config.NEMOTRON_NANO_MODEL),
        ("Tier 2 — Super 120B (MoE A12B)", config.NEMOTRON_SUPER_MODEL),
        ("Tier 3 — Ultra 550B (MoE A55B)", config.NEMOTRON_ULTRA_MODEL),
    ]
    total_calls_needed = len(tiers) * runs_per_tier
    quota = clients.consume_llm_quota(total_calls_needed, reason=f"benchmark:{runs_per_tier}x3")
    if not quota["allowed"]:
        raise RuntimeError(quota["reason"])

    tf_client = clients.token_factory()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    tier_summaries: list[dict[str, Any]] = []

    for tier_label, model_id in tiers:
        latencies: list[float] = []
        p_tokens_list: list[int] = []
        c_tokens_list: list[int] = []
        costs_list: list[float] = []
        sample_output = ""
        pricing = config.NEBIUS_MODEL_PRICING.get(
            model_id, {"input_per_1m": 1.00, "output_per_1m": 3.00}
        )

        for _ in range(runs_per_tier):
            t0 = time.perf_counter()
            resp = tf_client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a concise clinical pharmacogenomics assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=180,
                extra_body={"chat_template_kwargs": {"enable_thinking": bool(enable_thinking)}},
            )
            dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            latencies.append(dt_ms)
            p_tok = int(getattr(resp.usage, "prompt_tokens", 0) or 0) if resp.usage else 0
            c_tok = int(getattr(resp.usage, "completion_tokens", 0) or 0) if resp.usage else 0
            p_tokens_list.append(p_tok)
            c_tokens_list.append(c_tok)
            c_usd = (p_tok * pricing["input_per_1m"] + c_tok * pricing["output_per_1m"]) / 1_000_000.0
            costs_list.append(round(c_usd, 6))
            msg = resp.choices[0].message
            txt = (msg.content or getattr(msg, "reasoning_content", "") or "").strip()
            if txt:
                sample_output = txt

        tier_summaries.append(
            {
                "tier": tier_label,
                "model": model_id,
                "runs_per_tier": runs_per_tier,
                "median_latency_ms": round(statistics.median(latencies), 1),
                "min_latency_ms": round(min(latencies), 1),
                "max_latency_ms": round(max(latencies), 1),
                "latencies_ms": latencies,
                "mean_prompt_tokens": round(statistics.mean(p_tokens_list), 1),
                "mean_completion_tokens": round(statistics.mean(c_tokens_list), 1),
                "mean_cost_usd": round(statistics.mean(costs_list), 6),
                "input_price_per_1m_usd": pricing["input_per_1m"],
                "output_price_per_1m_usd": pricing["output_per_1m"],
                "sample_output": sample_output[:320],
            }
        )

    doc = {
        "benchmark_id": "latest_3tier_benchmark",
        "measured_at": now_iso,
        "runs_per_tier": runs_per_tier,
        "total_llm_calls": total_calls_needed,
        "prompt": prompt,
        "tiers": tier_summaries,
    }
    clients.state_store().collection(config.COLL_BENCHMARKS).document("latest_3tier_benchmark").set(doc)
    return doc


def get_persisted_benchmarks() -> dict[str, Any] | None:
    """Reads the latest persisted 3-tier benchmark document from `benchmarks`."""
    snap = (
        clients.state_store()
        .collection(config.COLL_BENCHMARKS)
        .document("latest_3tier_benchmark")
        .get()
    )
    return snap.to_dict() if snap.exists else None
