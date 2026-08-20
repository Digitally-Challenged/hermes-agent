#!/usr/bin/env python3
"""Summarize a vLLM server's Prometheus /metrics into human-readable stats.

Stdlib only. Fetches the metrics endpoint (default http://localhost:8000/metrics),
parses the Prometheus text format, and prints per-model throughput and cache
figures: prefill tok/s, decode tok/s, time-to-first-token, prefix-cache hit
rate, KV-cache usage, and request counts.

Usage:
    python3 vllm_metrics.py [--url URL] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

_SAMPLE_RE = re.compile(
    r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'(?:\{(?P<labels>[^}]*)\})?'
    r'\s+(?P<value>[^\s]+)'
)
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_prometheus_text(text: str) -> dict[str, dict[str, float]]:
    """Return {metric_name: {model_name_or_'': value}} for vllm:* samples.

    Histogram bucket lines are skipped; only _sum/_count/gauge/counter samples
    are kept. When several samples share a metric name (multi-model servers),
    they are keyed by their model_name label.
    """
    out: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        if not line.startswith("vllm:"):
            continue
        if "_bucket{" in line:
            continue
        m = _SAMPLE_RE.match(line)
        if not m:
            continue
        try:
            value = float(m.group("value"))
        except ValueError:
            continue
        labels = dict(_LABEL_RE.findall(m.group("labels") or ""))
        model = labels.get("model_name", "")
        name = m.group("name")
        by_model = out.setdefault(name, {})
        # Counters can be split across extra labels (e.g. request_success_total
        # by finished_reason) — sum those; for gauges the last sample wins.
        if name.endswith("_total") and model in by_model:
            by_model[model] += value
        else:
            by_model[model] = value
    return out


def _first(metrics: dict, name: str, model: str) -> float | None:
    by_model = metrics.get(name)
    if not by_model:
        return None
    if model in by_model:
        return by_model[model]
    return next(iter(by_model.values()), None)


def summarize(metrics: dict[str, dict[str, float]]) -> list[dict]:
    """Compute per-model summary stats from parsed vllm metrics."""
    models = set()
    for by_model in metrics.values():
        models.update(by_model)
    if len(models) > 1:
        # Unlabeled engine-level samples ("" model) duplicate the labeled rows.
        models.discard("")
    summaries = []
    for model in sorted(models):
        g = lambda name: _first(metrics, name, model)  # noqa: E731

        prompt_tok = g("vllm:request_prompt_tokens_sum")
        prefill_s = g("vllm:request_prefill_time_seconds_sum")
        itl_sum = g("vllm:inter_token_latency_seconds_sum")
        itl_count = g("vllm:inter_token_latency_seconds_count")
        ttft_sum = g("vllm:time_to_first_token_seconds_sum")
        ttft_count = g("vllm:time_to_first_token_seconds_count")
        cache_hits = g("vllm:prefix_cache_hits_total")
        cache_queries = g("vllm:prefix_cache_queries_total")

        def _ratio(num, den):
            if num is None or not den:
                return None
            return num / den

        summaries.append({
            "model": model or "(unlabeled)",
            "requests": g("vllm:request_success_total"),
            "running": g("vllm:num_requests_running"),
            "waiting": g("vllm:num_requests_waiting"),
            "prompt_tokens_total": g("vllm:prompt_tokens_total"),
            "generation_tokens_total": g("vllm:generation_tokens_total"),
            "prefill_tok_per_s": _ratio(prompt_tok, prefill_s),
            "decode_tok_per_s": _ratio(itl_count, itl_sum),
            "avg_ttft_s": _ratio(ttft_sum, ttft_count),
            "prefix_cache_hit_rate": _ratio(cache_hits, cache_queries),
            "kv_cache_usage": g("vllm:kv_cache_usage_perc"),
        })
    return summaries


def format_summary(summaries: list[dict]) -> str:
    lines = []
    for s in summaries:
        def fmt(v, spec="{:,.0f}", none="n/a"):
            return none if v is None else spec.format(v)

        lines.append(f"model: {s['model']}")
        lines.append(
            f"  throughput: prefill {fmt(s['prefill_tok_per_s'], '{:,.0f}')} tok/s | "
            f"decode {fmt(s['decode_tok_per_s'], '{:,.1f}')} tok/s | "
            f"avg TTFT {fmt(s['avg_ttft_s'], '{:,.1f}')} s"
        )
        hit = s["prefix_cache_hit_rate"]
        kv = s["kv_cache_usage"]
        lines.append(
            f"  caches: prefix hit rate "
            f"{'n/a' if hit is None else f'{hit:.1%}'} | KV usage "
            f"{'n/a' if kv is None else f'{kv:.1%}'}"
        )
        lines.append(
            f"  lifetime: {fmt(s['requests'])} requests | "
            f"{fmt(s['prompt_tokens_total'])} prompt tok | "
            f"{fmt(s['generation_tokens_total'])} generated tok | "
            f"running {fmt(s['running'])} / waiting {fmt(s['waiting'])}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8000/metrics")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()
    try:
        with urllib.request.urlopen(args.url, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"error: could not fetch {args.url}: {exc}", file=sys.stderr)
        return 1
    summaries = summarize(parse_prometheus_text(text))
    if not summaries:
        print("error: no vllm:* metrics found — is this a vLLM server?", file=sys.stderr)
        return 1
    print(json.dumps(summaries, indent=2) if args.json else format_summary(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
