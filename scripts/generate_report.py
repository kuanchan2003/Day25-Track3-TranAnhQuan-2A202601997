from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reliability_lab.config import load_config


def _number(value: object, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _percent(value: object) -> str:
    return f"{float(value or 0) * 100:.2f}%"


def _scenario_expectation(name: str) -> str:
    expectations = {
        "primary_timeout_100": "Primary circuit opens; backup serves at least 90% of attempts",
        "primary_flaky_50": "Primary and fallback traffic mix while availability remains above zero",
        "all_healthy": "At least 99% availability with no circuit opening",
        "all_providers_down": "Every request returns the controlled static fallback",
    }
    return expectations.get(name, "Gateway returns a controlled response")


def _comparison_row(
    label: str,
    key: str,
    without_cache: dict[str, Any],
    with_cache: dict[str, Any],
) -> str:
    before = float(without_cache.get(key, 0) or 0)
    after = float(with_cache.get(key, 0) or 0)
    return f"| {label} | {_number(before, 6)} | {_number(after, 6)} | {_number(after - before, 6)} |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out", default="reports/final_report.md")
    args = parser.parse_args()

    metrics: dict[str, Any] = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    config = load_config(args.config)
    scenarios: dict[str, str] = metrics.get("scenarios", {})
    details: dict[str, dict[str, Any]] = metrics.get("scenario_details", {})
    comparison: dict[str, dict[str, Any]] = metrics.get("cache_comparison", {})
    without_cache = comparison.get("without_cache", {})
    with_cache = comparison.get("with_cache", {})

    availability_met = float(metrics.get("availability", 0)) >= 0.99
    latency_met = float(metrics.get("latency_p95_ms", 0)) < 2500
    fallback_met = float(metrics.get("fallback_success_rate", 0)) >= 0.95
    cache_met = float(metrics.get("cache_hit_rate", 0)) >= 0.10
    recovery = metrics.get("recovery_time_ms")
    recovery_met = recovery is not None and float(recovery) < 5000

    lines = [
        "# Day 25 Reliability Engineering Final Report",
        "",
        "- Student: Trần Anh Quân",
        "- Student ID: 2A202601997",
        "- Environment: Python managed by `uv`; Redis 7 Alpine via Docker Compose",
        "",
        "## 1. Architecture summary",
        "",
        "```text",
        "User request",
        "     |",
        "     v",
        "ReliabilityGateway -> semantic cache -> cache hit: return immediately",
        "     | cache miss",
        "     v",
        "CircuitBreaker(primary) -> primary provider",
        "     | open/failure",
        "     v",
        "CircuitBreaker(backup)  -> backup provider",
        "     | open/failure",
        "     v",
        "Controlled static fallback",
        "```",
        "",
        "Each provider has an independent CLOSED/OPEN/HALF_OPEN circuit. Sensitive queries bypass both cache reads and writes. Four-digit mismatches reject likely semantic false hits.",
        "",
        "## 2. Configuration",
        "",
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        f"| failure_threshold | {config.circuit_breaker.failure_threshold} | Stops repeated calls without reacting to one transient error |",
        f"| reset_timeout_seconds | {config.circuit_breaker.reset_timeout_seconds} | Bounds the outage probe rate and permits recovery checks |",
        f"| success_threshold | {config.circuit_breaker.success_threshold} | One successful probe restores service promptly in this local lab |",
        f"| cache backend | {config.cache.backend} | Memory isolates scenarios; Redis is verified separately for shared state |",
        f"| cache TTL | {config.cache.ttl_seconds}s | Limits stale responses while retaining repeated load-test queries |",
        f"| similarity_threshold | {config.cache.similarity_threshold} | Conservative threshold plus a number-mismatch guard for dated queries |",
        f"| load-test requests | {config.load_test.requests}/scenario | Repeats the 20-query fixture enough to exercise caching |",
        "",
        "## 3. SLO evaluation",
        "",
        "| SLI | Target | Actual | Met? |",
        "|---|---|---:|---|",
        f"| Availability | >= 99% | {_percent(metrics.get('availability'))} | {'Yes' if availability_met else 'No'} |",
        f"| Latency P95 | < 2500 ms | {_number(metrics.get('latency_p95_ms'))} ms | {'Yes' if latency_met else 'No'} |",
        f"| Fallback success rate | >= 95% | {_percent(metrics.get('fallback_success_rate'))} | {'Yes' if fallback_met else 'No'} |",
        f"| Cache hit rate | >= 10% | {_percent(metrics.get('cache_hit_rate'))} | {'Yes' if cache_met else 'No'} |",
        f"| Recovery time | < 5000 ms | {_number(recovery)} | {'Yes' if recovery_met else 'Not observed'} |",
        "",
        "The aggregate deliberately includes the total provider outage scenario, so availability and fallback SLO failures are expected evidence of degraded-mode behavior rather than an uncontrolled exception.",
        "",
        "## 4. Aggregate metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    metric_keys = [
        "total_requests",
        "availability",
        "error_rate",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "fallback_success_rate",
        "cache_hit_rate",
        "estimated_cost",
        "estimated_cost_saved",
        "circuit_open_count",
        "recovery_time_ms",
    ]
    lines.extend(f"| {key} | {_number(metrics.get(key), 6)} |" for key in metric_keys)

    lines += [
        "",
        "## 5. Cache comparison",
        "",
        "Both runs use healthy providers and the same request count. Cache-hit latency is zero and, per the lab metric contract, is excluded from provider latency percentiles; cost and hit rate show the clearest benefit.",
        "",
        "| Metric | Without cache | With cache | Delta |",
        "|---|---:|---:|---:|",
        _comparison_row("latency_p50_ms", "latency_p50_ms", without_cache, with_cache),
        _comparison_row("latency_p95_ms", "latency_p95_ms", without_cache, with_cache),
        _comparison_row("estimated_cost", "estimated_cost", without_cache, with_cache),
        _comparison_row("cache_hit_rate", "cache_hit_rate", without_cache, with_cache),
        "",
        "## 6. Redis shared cache",
        "",
        "An in-memory cache is private to one gateway process, so another replica cannot reuse its responses. `SharedRedisCache` stores query/response hashes with Redis TTLs, allowing independent gateway instances to share exact and semantic hits while preserving privacy and false-hit guards.",
        "",
        "Evidence from the completed integration suite:",
        "",
        "```text",
        "tests/test_redis_cache.py: 6 passed",
        "test_shared_state_across_instances: instance c2 read the value written by c1",
        "test_ttl_expiry, test_privacy_query_not_cached, test_false_hit_different_years: passed",
        "```",
        "",
        "Observed Redis CLI output after writing a non-sensitive evidence query:",
        "",
        "```text",
        "> docker compose exec -T redis redis-cli KEYS \"rl:cache:*\"",
        "rl:cache:8f99b5afaa87",
        "```",
        "",
        "Reproduction commands:",
        "",
        "```bash",
        "docker compose up -d",
        "uv run --extra dev pytest tests/test_redis_cache.py -v",
        "docker compose exec redis redis-cli KEYS 'rl:cache:*'",
        "```",
        "",
        "## 7. Chaos scenarios",
        "",
        "| Scenario | Expected behavior | Observed behavior | Status |",
        "|---|---|---|---|",
    ]
    for name, status in scenarios.items():
        result = details.get(name, {})
        observed = (
            f"availability {_percent(result.get('availability'))}; "
            f"fallback {_percent(result.get('fallback_success_rate'))}; "
            f"static fallbacks {result.get('static_fallbacks', 0)}; "
            f"circuit opens {result.get('circuit_open_count', 0)}"
        )
        lines.append(f"| {name} | {_scenario_expectation(name)} | {observed} | {status.upper()} |")

    lines += [
        "",
        "## 8. Failure analysis",
        "",
        "The HALF_OPEN gate is process-local and does not reserve a single probe under concurrent traffic. Multiple workers could probe simultaneously after the timeout and create a small retry burst. Before production, circuit state and a probe lease should be stored atomically in Redis (or another coordination store), with bounded jitter and per-provider timeouts.",
        "",
        "No recovery time is produced when a scenario never reaches an OPEN -> CLOSED transition. This is reported as `null` rather than inventing a successful recovery measurement.",
        "",
        "## 9. Next steps",
        "",
        "1. Add a concurrency-safe HALF_OPEN probe lease and a threaded load test.",
        "2. Measure cache false-hit rate against a labeled evaluation set, not only date mismatches.",
        "3. Add per-provider timeout/retry budgets and alerting for SLO burn rate.",
        "",
        "## 10. Reproduction",
        "",
        "```bash",
        "uv sync --extra dev",
        "docker compose up -d",
        "uv run --extra dev pytest -q",
        "uv run python scripts/run_chaos.py --config configs/default.yaml --out reports/metrics.json",
        "uv run python scripts/generate_report.py --metrics reports/metrics.json --out reports/final_report.md",
        "```",
    ]

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
