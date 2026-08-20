"""Tests for the vllm-metrics optional skill's summarizer script."""

import importlib.util
import pathlib

SKILL_DIR = pathlib.Path(__file__).resolve().parents[2] / "optional-skills" / "mlops" / "vllm-metrics"
SCRIPT = SKILL_DIR / "scripts" / "vllm_metrics.py"

spec = importlib.util.spec_from_file_location("vllm_metrics", SCRIPT)
vllm_metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vllm_metrics)

SNAPSHOT = """\
# HELP vllm:prompt_tokens_total Number of prefill tokens processed.
# TYPE vllm:prompt_tokens_total counter
vllm:prompt_tokens_total{engine="0",model_name="qwen3.8-27b"} 960968.0
# TYPE vllm:generation_tokens_total counter
vllm:generation_tokens_total{engine="0",model_name="qwen3.8-27b"} 17810.0
# TYPE vllm:prefix_cache_queries_total counter
vllm:prefix_cache_queries_total{engine="0",model_name="qwen3.8-27b"} 1000000.0
# TYPE vllm:prefix_cache_hits_total counter
vllm:prefix_cache_hits_total{engine="0",model_name="qwen3.8-27b"} 860000.0
# TYPE vllm:kv_cache_usage_perc gauge
vllm:kv_cache_usage_perc{engine="0",model_name="qwen3.8-27b"} 0.081
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="qwen3.8-27b"} 1.0
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{engine="0",model_name="qwen3.8-27b"} 0.0
# TYPE vllm:request_success_total counter
vllm:request_success_total{engine="0",finished_reason="stop",model_name="qwen3.8-27b"} 30.0
vllm:request_success_total{engine="0",finished_reason="length",model_name="qwen3.8-27b"} 9.0
# TYPE vllm:request_prompt_tokens histogram
vllm:request_prompt_tokens_bucket{le="100",model_name="qwen3.8-27b"} 0.0
vllm:request_prompt_tokens_sum{engine="0",model_name="qwen3.8-27b"} 900000.0
vllm:request_prompt_tokens_count{engine="0",model_name="qwen3.8-27b"} 39.0
# TYPE vllm:request_prefill_time_seconds histogram
vllm:request_prefill_time_seconds_sum{engine="0",model_name="qwen3.8-27b"} 900.0
vllm:request_prefill_time_seconds_count{engine="0",model_name="qwen3.8-27b"} 39.0
# TYPE vllm:inter_token_latency_seconds histogram
vllm:inter_token_latency_seconds_sum{engine="0",model_name="qwen3.8-27b"} 1700.0
vllm:inter_token_latency_seconds_count{engine="0",model_name="qwen3.8-27b"} 17000.0
# TYPE vllm:time_to_first_token_seconds histogram
vllm:time_to_first_token_seconds_sum{engine="0",model_name="qwen3.8-27b"} 1080.0
vllm:time_to_first_token_seconds_count{engine="0",model_name="qwen3.8-27b"} 40.0
# Engine-level sample without a model label (some builds emit these):
vllm:num_preemptions_total{engine="0"} 0.0
"""


class TestParse:
    def test_skips_buckets_and_non_vllm_lines(self):
        metrics = vllm_metrics.parse_prometheus_text(SNAPSHOT)
        assert "vllm:request_prompt_tokens_bucket" not in metrics
        assert all(k.startswith("vllm:") for k in metrics)

    def test_counters_split_by_extra_labels_are_summed(self):
        metrics = vllm_metrics.parse_prometheus_text(SNAPSHOT)
        assert metrics["vllm:request_success_total"]["qwen3.8-27b"] == 39.0

    def test_gauge_last_sample_wins_not_summed(self):
        metrics = vllm_metrics.parse_prometheus_text(SNAPSHOT)
        assert metrics["vllm:kv_cache_usage_perc"]["qwen3.8-27b"] == 0.081


class TestSummarize:
    def _summary(self):
        metrics = vllm_metrics.parse_prometheus_text(SNAPSHOT)
        summaries = vllm_metrics.summarize(metrics)
        assert len(summaries) == 1  # unlabeled engine row folded away
        return summaries[0]

    def test_throughput_math(self):
        s = self._summary()
        assert s["model"] == "qwen3.8-27b"
        assert s["prefill_tok_per_s"] == 1000.0  # 900000 / 900
        assert s["decode_tok_per_s"] == 10.0  # 17000 / 1700
        assert s["avg_ttft_s"] == 27.0  # 1080 / 40

    def test_cache_and_counts(self):
        s = self._summary()
        assert s["prefix_cache_hit_rate"] == 0.86
        assert s["requests"] == 39.0

    def test_missing_metrics_yield_none_not_crash(self):
        summaries = vllm_metrics.summarize(
            vllm_metrics.parse_prometheus_text(
                'vllm:prompt_tokens_total{model_name="m"} 5.0\n'
            )
        )
        assert summaries[0]["decode_tok_per_s"] is None
        assert summaries[0]["prefix_cache_hit_rate"] is None

    def test_format_summary_handles_none(self):
        metrics = vllm_metrics.parse_prometheus_text(
            'vllm:prompt_tokens_total{model_name="m"} 5.0\n'
        )
        text = vllm_metrics.format_summary(vllm_metrics.summarize(metrics))
        assert "n/a" in text and "m" in text
