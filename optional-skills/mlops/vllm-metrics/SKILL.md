---
name: vllm-metrics
description: Report a local vLLM server live throughput and cache stats.
version: 0.1.0
author: Nick Coleman (nickcoleman85), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [vLLM, Metrics, Prometheus, LocalLLM, Throughput, Observability]
    related_skills: []
---

# vLLM Metrics Skill

Answer "how fast are you running?" with real numbers instead of guesses. When
Hermes itself (or any local app) runs on a vLLM server, this skill reads the
server's Prometheus `/metrics` endpoint and reports prefill/decode throughput,
time-to-first-token, prefix-cache hit rate, and KV-cache usage. It does not
manage, restart, or benchmark the server — it only reads counters.

## When to Use

- The user asks "what's your tok/sec", "how fast is the local model", "is the
  prefix cache working", or similar self-performance questions
- Diagnosing whether a slow turn was prefill-bound, decode-bound, or queued
- Verifying prefix caching is effective after a config or model change

Not for LM Studio or Ollama — they don't expose vLLM's Prometheus metrics.

## Prerequisites

- A vLLM (or vllm-metal) server reachable over HTTP. Default assumed endpoint:
  `http://localhost:8000/metrics`. Ask the user for the port if 8000 fails.
- Python 3 available to the `terminal` tool (stdlib only, no packages).

## How to Run

Run the bundled summarizer via the `terminal` tool:

```bash
python3 scripts/vllm_metrics.py                 # human-readable summary
python3 scripts/vllm_metrics.py --json          # machine-readable
python3 scripts/vllm_metrics.py --url http://HOST:PORT/metrics
```

## Quick Reference

| Reported figure | Derived from |
|---|---|
| prefill tok/s | `request_prompt_tokens_sum / request_prefill_time_seconds_sum` |
| decode tok/s | `inter_token_latency_seconds_count / _sum` |
| avg TTFT | `time_to_first_token_seconds_sum / _count` |
| prefix-cache hit rate | `prefix_cache_hits_total / prefix_cache_queries_total` |
| KV usage | `kv_cache_usage_perc` gauge |

All counters are lifetime totals since server start, so the throughput numbers
are averages over the server's whole uptime, not the last request.

## Procedure

1. Run `scripts/vllm_metrics.py` with the `terminal` tool. If the default URL
   fails, ask the user for the server's port before retrying.
2. Relay the summary conversationally. Lead with what the user asked for
   (usually decode tok/s); include the cache hit rate when discussing speed —
   a low hit rate on a chat workload usually means prefix caching is off or
   the prompt prefix is churning.
3. For "why was that turn slow": compare avg TTFT (prefill cost) against
   decode tok/s, and check `waiting` for queueing.

## Pitfalls

- Lifetime averages hide variance: one giant cold prefill drags avg TTFT far
  above the warm-turn experience. Say "average since server start" when
  reporting.
- A `(unlabeled)` model row appears on some builds for engine-level samples;
  the script already folds it away when a labeled model exists.
- `request_success_total` is split by finish reason; the script sums the
  splits — don't re-read raw metrics and report a single split as the total.

## Verification

`scripts/run_tests.sh tests/skills/test_vllm_metrics_skill.py -q` — parser and
summary math against a canned metrics snapshot; no network.
