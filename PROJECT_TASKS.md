# AutoOps Project Tasks

This task list tracks the remaining work needed to bring AutoOps in line with the PRD and make the demo production-like.

## P0 - Critical

- [x] Replace Monitoring demo data with real CloudWatch-backed service health.
  - Removed deterministic `SERVICE_PROFILES` demo data.
  - Read `ErrorRate`, `Latency`, and alarm state from CloudWatch.
  - Kept structured error responses for missing AWS credentials or missing metrics.
  - Added boto3-mocked tests for health, deployment history, and incident summaries.

- [x] Complete the end-to-end incident triage flow.
  - Prompt: `Error rate on checkout-service spiked. Triage and create an incident issue.`
  - Query CloudWatch data.
  - Pull deployment history.
  - Pull recent GitHub commits.
  - Compose a GitHub issue body with findings.
  - Pause for HITL approval before creating the issue.

- [x] Expand GitHub Agent tool coverage.
  - Added `get_pr_diff(pr_number)`.
  - Added `add_pr_comment(pr_number, comment)`.
  - Routed `add_pr_comment` through HITL as a write operation.
  - Added unit tests for both tools and approval behavior.

## P1 - PRD Alignment

- [x] Upgrade Code Review tools.
  - Added `flake8` for Python linting with `py_compile` fallback.
  - Added `bandit` for Python security scanning when available.
  - Added npm lint/audit hooks when package metadata is present.
  - Kept lightweight local fallback behavior when tools are unavailable.

- [x] Add FastAPI graph wrapper.
  - Implemented `POST /run`.
  - Implemented `POST /approve`.
  - Implemented `GET /agents`.
  - Added integration tests for the API wrapper.

- [x] Improve A2A lifecycle and streaming.
  - Emits `submitted -> working -> completed` lifecycle states.
  - Implemented SSE support for `stream_delegate()`.
  - Added tests for streaming success paths.

- [x] Add observability hooks.
  - Added LangSmith-style `run_name`, `tags`, and `metadata` to graph invocations.
  - Added optional tool-call spans around MCP calls.
  - Added A2A delegation spans with target agent, task type, and duration.
  - Documented required tracing environment variables.

## P2 - Production Readiness

- [x] Add Docker and docker-compose support.
  - Containerized all 4 MCP servers.
  - Added gateway/API service.
  - Runs MCP servers with SSE transport in containers.
  - `docker compose up --build` is documented.

- [x] Add SSE MCP client support in agents.
  - Keeps stdio transport for local development.
  - Uses SSE transport when configured for Docker/cloud.
  - Added transport selection tests.

- [x] Add AgentCore deployment skeleton.
  - Added `agentcore/config.yaml`.
  - Added `agentcore/policies/write_gate.cedar`.
  - Documented deployment files in README.

- [x] Harden security configuration.
  - A2A bearer auth is supported.
  - GitHub writes remain gated by HITL.
  - Cedar write-gate policy scaffold is included.

## P3 - Polish

- [x] Expand test coverage.
  - Added Monitoring tests with mocked CloudWatch responses.
  - Added API wrapper integration coverage.
  - Added GitHub MCP and HITL write coverage.
  - Added MCP transport selection tests.

- [x] Update README with project operation docs.
  - Documented real service requirements.
  - Added the canonical demo scenario command.
  - Added API, Docker, and AgentCore sections.

- [x] Add CI.
  - Installs dependencies.
  - Runs Python compile check.
  - Runs `python -m pytest`.

## Recommended Order

1. Real CloudWatch-backed Monitoring Agent.
2. End-to-end incident issue flow.
3. Missing GitHub tools.
4. FastAPI graph wrapper.
5. Docker and SSE transport.
6. Observability.
7. AgentCore skeleton.

## Current Starting Point

- GitHub MCP tools are real via `gh` CLI.
- CloudWatch MCP tools are real via boto3.
- Code Review MCP tools are local real tools with lightweight implementations.
- Monitoring MCP tools now read CloudWatch metrics, active alarms, and deployment logs.
- Current full test suite status after project completion pass: `72 passed`.
