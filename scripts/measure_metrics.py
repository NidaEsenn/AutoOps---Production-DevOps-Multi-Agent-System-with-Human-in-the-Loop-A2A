"""Measure routing accuracy and end-to-end latency for AutoOps.

Routing accuracy: run the LLM supervisor on a labeled prompt set and compare the
chosen agent to the expected one.
End-to-end latency: run the full LangGraph (warm, in-process) on read-path
requests and time each from prompt to completion.
"""

import asyncio
import statistics
import time

from autoops.state import initial_state
from autoops.supervisor import build_graph, llm_route

# (prompt, expected_agent) — phrased naturally, not copied from the keyword table.
DATASET = [
    ("list the open pull requests", "github"),
    ("what commits landed on main recently?", "github"),
    ("show me the repository status", "github"),
    ("create an issue to track the flaky login test", "github"),
    ("tail the error logs for the api service", "cloudwatch"),
    ("are there any alarms currently firing?", "cloudwatch"),
    ("pull the request latency metrics for the last hour", "cloudwatch"),
    ("what does cloudwatch show for worker error rates?", "cloudwatch"),
    ("run a security scan over the codebase", "codereview"),
    ("lint the supervisor file for style issues", "codereview"),
    ("check our python code for known vulnerabilities", "codereview"),
    ("do a static analysis pass on the auth module", "codereview"),
    ("is the checkout-service healthy right now?", "monitoring"),
    ("show me the recent deployment history for payments", "monitoring"),
    ("give me an incident summary for the checkout-service", "monitoring"),
    ("what is the overall service status?", "monitoring"),
    ("what is a good recipe for dinner?", "end"),
    ("tell me a joke about cats", "end"),
]

# Read-path prompts used for end-to-end latency (exclude write + trivial-end).
LATENCY_PROMPTS = [
    "show me the repository status",
    "are there any alarms currently firing?",
    "lint the supervisor file for style issues",
    "is the checkout-service healthy right now?",
    "give me an incident summary for the checkout-service",
    "what does cloudwatch show for worker error rates?",
]


async def measure_routing():
    correct, total, rows = 0, 0, []
    for prompt, expected in DATASET:
        decision = await llm_route(prompt)
        got = decision.next_agent if decision else "(llm-failed)"
        ok = got == expected
        correct += ok
        total += 1
        rows.append((ok, expected, got, prompt))
    return correct, total, rows


async def measure_latency():
    graph = build_graph()
    await graph.ainvoke(initial_state("show me the repository status", "warmup"))  # warm caches
    times = []
    for i, prompt in enumerate(LATENCY_PROMPTS):
        t0 = time.time()
        await graph.ainvoke(initial_state(prompt, f"lat-{i}"))
        times.append((prompt, time.time() - t0))
    return times


async def main():
    print("=" * 70)
    print("ROUTING ACCURACY (LLM supervisor)")
    print("=" * 70)
    correct, total, rows = await measure_routing()
    for ok, exp, got, prompt in rows:
        mark = "OK " if ok else "XX "
        print(f"  {mark} expected={exp:11} got={got:11} | {prompt}")
    print(f"\n  ACCURACY: {correct}/{total} = {100*correct/total:.1f}%")

    print("\n" + "=" * 70)
    print("END-TO-END LATENCY (full graph, warm, in-process)")
    print("=" * 70)
    times = await measure_latency()
    durs = [d for _, d in times]
    for prompt, d in times:
        print(f"  {d:6.2f}s | {prompt}")
    durs_sorted = sorted(durs)
    p95 = durs_sorted[max(0, round(0.95 * len(durs_sorted)) - 1)]
    print(f"\n  {len(durs)} requests | median={statistics.median(durs):.2f}s "
          f"| p95={p95:.2f}s | min={min(durs):.2f}s | max={max(durs):.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
