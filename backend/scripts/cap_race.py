"""Proves the click cap holds under concurrency. Demo this live.

    python -m scripts.cap_race --api http://localhost:8000 --cap 100 --requests 1000 --concurrency 200

Creates a fresh link capped at --cap, fires --requests simultaneous visits with a
real browser user agent, and checks that EXACTLY --cap of them were redirected.
A naive "read count, then update" implementation lets extra visitors through here.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


async def main(api: str, cap: int, total: int, concurrency: int, email: str, password: str) -> None:
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        token = r.json()["token"]
        r = await client.post("/api/links", headers={"Authorization": f"Bearer {token}"},
                              json={"destination": "https://example.com/cap-test", "title": f"Cap race {cap}",
                                    "click_cap": cap})
        r.raise_for_status()
        link = r.json()
        print(f"Created {link['short_url']} with a cap of {cap}. Firing {total} requests...")

    path = "/" + link["code"]
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(base_url=api, timeout=30, follow_redirects=False, limits=limits,
                                 headers={"User-Agent": BROWSER_UA}) as client:
        async def hit(i: int) -> None:
            async with sem:
                t0 = time.perf_counter()
                # Distinct X-Forwarded-For per request so burst detection sees different visitors
                # (only honored when TRUST_PROXY_HEADERS=true).
                resp = await client.get(path, headers={"X-Forwarded-For": f"10.0.{i // 250}.{i % 250 + 1}"})
                latencies.append((time.perf_counter() - t0) * 1000)
                statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1

        t_start = time.perf_counter()
        await asyncio.gather(*(hit(i) for i in range(total)))
        elapsed = time.perf_counter() - t_start

    redirected = statuses.get(302, 0)
    q = statistics.quantiles(latencies, n=100)
    print(f"\nStatus codes: {dict(sorted(statuses.items()))}")
    print(f"Redirected:   {redirected}  (expected exactly {cap})")
    print(f"Limit page:   {statuses.get(410, 0)}")
    print(f"Latency ms:   p50={q[49]:.1f}  p95={q[94]:.1f}  p99={q[98]:.1f}  ({total / elapsed:.0f} req/s)")
    print("RESULT:", "PASS - the cap held under concurrency" if redirected == cap else "FAIL - cap overshoot")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--cap", type=int, default=100)
    p.add_argument("--requests", type=int, default=1000)
    p.add_argument("--concurrency", type=int, default=200)
    p.add_argument("--email", default="demo@linkpulse.dev")
    p.add_argument("--password", default="Demo@12345")
    a = p.parse_args()
    asyncio.run(main(a.api, a.cap, a.requests, a.concurrency, a.email, a.password))
