# AutoOps — AWS Bedrock AgentCore Deployment

Production deployment record for **AutoOps**, a multi-agent DevOps assistant
(LangGraph supervisor → GitHub / CloudWatch / Code Review / Monitoring
specialist agents, MCP tool servers, A2A protocol, human-in-the-loop write
gates, and LangSmith/Logfire observability).

## Deployment summary

| | |
|---|---|
| Platform | Amazon Bedrock **AgentCore** Runtime |
| Deployment mode | `direct_code_deploy` (Python 3.13, ARM64) |
| Region / Account | `us-east-1` / `<ACCOUNT_ID>` |
| Agent ARN | `arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:runtime/autoops-rcaKbr5dgn` |
| Entry point | `agentcore_app.py` → `BedrockAgentCoreApp` (`POST /invocations`, `GET /ping`) |
| LLM | Groq `llama-3.3-70b-versatile` (structured-output routing) |
| IAM | Dedicated execution role; least-privilege CloudWatch read for the agents |
| Tests | 77 passing (unit + integration) |

## Architecture

```
invoke {"task": "..."}
        │
        ▼
  AgentCore Runtime  ──►  agentcore_app.py (BedrockAgentCoreApp entrypoint)
        │
        ▼
  LangGraph Supervisor ── LLM routing (Groq, structured output)
   ├─ GitHub agent      → MCP tools (gh CLI)         [write → HITL gate]
   ├─ CloudWatch agent  → MCP tools (boto3)
   ├─ Code Review agent → MCP tools (flake8/bandit)  + A2A server
   └─ Monitoring agent  → MCP tools (CloudWatch health)
        │
   Observability: AgentCore CloudWatch + X-Ray; LangSmith + Logfire
```

## Verified live invocations (AgentCore Runtime)

Each row is a real `InvokeAgentRuntime` call against the deployed agent, with
measured end-to-end latency:

| Task | Latency | Result |
|------|---------|--------|
| `list open pull requests` | **6.6 s** | Routed to **github** by LLM — *"related to pull requests, a GitHub workflow"* |
| `create an issue for checkout-service outage` | 32.0 s | **`approval_required`** → HITL gate on `create_issue` (no write without approval) |
| `show health for checkout-service` | **9.9 s** | **`degraded`** · error_rate **5.0%** · p95 latency **850 ms** · 1 active CloudWatch alarm |
| `run a security scan on autoops` | 21.4 s | Routed to **codereview** — scanned **4,715** files |

### Measured quality & performance (`scripts/measure_metrics.py`)

- **Routing accuracy: 18/18 (100%)** — the LLM supervisor routed an 18-prompt,
  naturally-phrased request set (GitHub / CloudWatch / Code Review / Monitoring /
  ambiguous) to the correct agent.
- **End-to-end latency (warm, local, full graph incl. real LLM + tool calls):**
  median **2.85 s**, p95 **3.69 s** across 6 read-path requests. On the deployed
  AgentCore runtime, warm end-to-end is ~6–7 s (adds `InvokeAgentRuntime`
  dispatch overhead).

### Performance optimization

The original design spawned each MCP server as a fresh subprocess on **every**
tool call (re-importing FastMCP + boto3 each time). Profiling the warm path
showed this cost ~2.2 s per call. Switching the default transport to an
**in-process FastMCP client** (loading each server module once, then reusing it)
cut the warm per-call MCP overhead from **2.2 s → 0.28 s (~8×)**. Subprocess
(`stdio`) and remote (`sse`) transports remain available for isolation /
distributed deployments.

End-to-end warm cloud latency is **~6–7 s** for read tasks; the remaining cost
is dominated by AgentCore `InvokeAgentRuntime` dispatch and the LLM routing
call, not MCP.

Key properties demonstrated end-to-end in the cloud:
- **LLM-driven routing** (Groq) — natural-language tasks dispatched to the right specialist.
- **Real AWS integration** — Monitoring agent reads live CloudWatch metrics + alarms via the execution role.
- **Human-in-the-loop safety** — write operations pause and return `approval_required` instead of executing.
- **Graceful degradation** — missing creds/permissions return structured errors, never crashes.

## Reproduce the deployment

```bash
# 1. Configure (generates .bedrock_agentcore.yaml)
AWS_PROFILE=autoops-deploy agentcore configure \
  -e agentcore_app.py -n autoops -r us-east-1 -rf requirements.txt \
  --disable-memory --non-interactive

# 2. Deploy (CodeBuild-free direct code deploy; inject the LLM key)
AWS_PROFILE=autoops-deploy agentcore deploy \
  --env GROQ_API_KEY=<key> --env GROQ_MODEL=llama-3.3-70b-versatile

# 3. Grant the auto-created execution role CloudWatch read
aws iam attach-role-policy --role-name <execution-role> \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess

# 4. Invoke
agentcore invoke '{"task": "show health for checkout-service"}'

# 5. Tear down (stop credit spend)
agentcore destroy --force
```

## Engineering notes (non-obvious fixes)

- **`mcp` package shadowing** — the runtime puts the entrypoint's directory on
  `sys.path`; a root-level `agentcore_app.py` keeps the repo root first so the
  `mcp` SDK isn't shadowed by the local `autoops/mcp/` package.
- **Read-only filesystem** — the HITL SQLite checkpoint is written to `/tmp`
  (the only writable path in the runtime).
- **Cold-start init** — heavy imports are loaded once; the runtime caches
  dependencies after the first initialization.

## Cost controls

- AWS Budget (`autoops-credit-50usd`) emails at $40 and $50 of gross spend.
- AgentCore Runtime is consumption-based (≈$0 idle); `agentcore destroy` removes
  the runtime, IAM role, and S3 artifacts when not demoing.
