# Day 25 Reliability Engineering Final Report

- Student: Trần Anh Quân
- Student ID: 2A202601997
- Environment: Python managed by `uv`; Redis 7 Alpine via Docker Compose

## 1. Architecture summary

```text
User request
     |
     v
ReliabilityGateway -> semantic cache -> cache hit: return immediately
     | cache miss
     v
CircuitBreaker(primary) -> primary provider
     | open/failure
     v
CircuitBreaker(backup)  -> backup provider
     | open/failure
     v
Controlled static fallback
```

Each provider has an independent CLOSED/OPEN/HALF_OPEN circuit. Sensitive queries bypass both cache reads and writes. Four-digit mismatches reject likely semantic false hits.

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Stops repeated calls without reacting to one transient error |
| reset_timeout_seconds | 2.0 | Bounds the outage probe rate and permits recovery checks |
| success_threshold | 1 | One successful probe restores service promptly in this local lab |
| cache backend | memory | Memory isolates scenarios; Redis is verified separately for shared state |
| cache TTL | 300s | Limits stale responses while retaining repeated load-test queries |
| similarity_threshold | 0.92 | Conservative threshold plus a number-mismatch guard for dated queries |
| load-test requests | 100/scenario | Repeats the 20-query fixture enough to exercise caching |

## 3. SLO evaluation

| SLI | Target | Actual | Met? |
|---|---|---:|---|
| Availability | >= 99% | 74.25% | No |
| Latency P95 | < 2500 ms | 317.85 ms | Yes |
| Fallback success rate | >= 95% | 37.58% | No |
| Cache hit rate | >= 10% | 46.50% | Yes |
| Recovery time | < 5000 ms | 2336.56 | Yes |

The aggregate deliberately includes the total provider outage scenario, so availability and fallback SLO failures are expected evidence of degraded-mode behavior rather than an uncontrolled exception.

## 4. Aggregate metrics

| Metric | Value |
|---|---:|
| total_requests | 400 |
| availability | 0.742500 |
| error_rate | 0.257500 |
| latency_p50_ms | 263.540000 |
| latency_p95_ms | 317.850000 |
| latency_p99_ms | 319.470000 |
| fallback_success_rate | 0.375800 |
| cache_hit_rate | 0.465000 |
| estimated_cost | 0.047714 |
| estimated_cost_saved | 0.186000 |
| circuit_open_count | 10 |
| recovery_time_ms | 2336.559772 |

## 5. Cache comparison

Both runs use healthy providers and the same request count. Cache-hit latency is zero and, per the lab metric contract, is excluded from provider latency percentiles; cost and hit rate show the clearest benefit.

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---:|
| latency_p50_ms | 209.030000 | 206.890000 | -2.140000 |
| latency_p95_ms | 238.490000 | 233.710000 | -4.780000 |
| estimated_cost | 0.058930 | 0.022500 | -0.036430 |
| cache_hit_rate | 0.000000 | 0.600000 | 0.600000 |

## 6. Redis shared cache

An in-memory cache is private to one gateway process, so another replica cannot reuse its responses. `SharedRedisCache` stores query/response hashes with Redis TTLs, allowing independent gateway instances to share exact and semantic hits while preserving privacy and false-hit guards.

Evidence from the completed integration suite:

```text
tests/test_redis_cache.py: 6 passed
test_shared_state_across_instances: instance c2 read the value written by c1
test_ttl_expiry, test_privacy_query_not_cached, test_false_hit_different_years: passed
```

Observed Redis CLI output after writing a non-sensitive evidence query:

```text
> docker compose exec -T redis redis-cli KEYS "rl:cache:*"
rl:cache:8f99b5afaa87
```

Reproduction commands:

```bash
docker compose up -d
uv run --extra dev pytest tests/test_redis_cache.py -v
docker compose exec redis redis-cli KEYS 'rl:cache:*'
```

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Status |
|---|---|---|---|
| primary_timeout_100 | Primary circuit opens; backup serves at least 90% of attempts | availability 97.00%; fallback 92.11%; static fallbacks 3; circuit opens 5 | PASS |
| primary_flaky_50 | Primary and fallback traffic mix while availability remains above zero | availability 100.00%; fallback 100.00%; static fallbacks 0; circuit opens 3 | PASS |
| all_healthy | At least 99% availability with no circuit opening | availability 100.00%; fallback 0.00%; static fallbacks 0; circuit opens 0 | PASS |
| all_providers_down | Every request returns the controlled static fallback | availability 0.00%; fallback 0.00%; static fallbacks 100; circuit opens 2 | PASS |

## 8. Failure analysis

The HALF_OPEN gate is process-local and does not reserve a single probe under concurrent traffic. Multiple workers could probe simultaneously after the timeout and create a small retry burst. Before production, circuit state and a probe lease should be stored atomically in Redis (or another coordination store), with bounded jitter and per-provider timeouts.

No recovery time is produced when a scenario never reaches an OPEN -> CLOSED transition. This is reported as `null` rather than inventing a successful recovery measurement.

## 9. Next steps

1. Add a concurrency-safe HALF_OPEN probe lease and a threaded load test.
2. Measure cache false-hit rate against a labeled evaluation set, not only date mismatches.
3. Add per-provider timeout/retry budgets and alerting for SLO burn rate.

## 10. Reproduction

```bash
uv sync --extra dev
docker compose up -d
uv run --extra dev pytest -q
uv run python scripts/run_chaos.py --config configs/default.yaml --out reports/metrics.json
uv run python scripts/generate_report.py --metrics reports/metrics.json --out reports/final_report.md
```
