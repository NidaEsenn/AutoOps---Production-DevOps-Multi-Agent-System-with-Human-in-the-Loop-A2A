`# AutoOps

AutoOps is a Python 3.11 DevOps multi-agent assistant. It routes natural-language operations tasks to specialist agents for GitHub workflows, CloudWatch investigation, local code review, and service monitoring.

The project uses LangGraph for orchestration, FastMCP for tool servers, FastAPI for agent-to-agent endpoints, and a human-in-the-loop approval flow for write actions.

## Features

- Supervisor routing for GitHub, CloudWatch, code review, and monitoring requests
- FastMCP tool servers for:
  - GitHub repository status, pull requests, and approved issue creation
  - CloudWatch logs, alarms, metrics, and deployment events
  - Local Python lint and lightweight security scanning
  - CloudWatch-backed service health, incidents, and deployment history
- Human approval before GitHub write operations
- A2A Code Review server with an Agent Card at `/.well-known/agent.json`
- Unit and integration tests for routing, agents, MCP tools, HITL, and A2A behavior

## Project Structure

```text
autoops/
  agents/        Specialist agent nodes
  a2a/           Agent-to-agent client, models, and FastAPI server
  mcp/           FastMCP tool servers
  hitl.py        Human approval loop for write actions
  main.py        CLI entry point
  state.py       Shared LangGraph state
  supervisor.py  Routing and graph definition
tests/
  unit/
  integration/
```

## Requirements

- Python 3.11+
- GitHub CLI (`gh`) for GitHub tools
- AWS credentials and region for CloudWatch tools

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

For local package-style development, you can also install the project in editable mode:

```bash
python3 -m pip install -e ".[dev]"
```

## Configuration

Useful environment variables:

```bash
export GITHUB_REPO="owner/repo"
export AWS_DEFAULT_REGION="us-east-1"
export DEPLOYMENT_LOG_GROUP="/aws/autoops/deployments"
export MONITORING_METRIC_NAMESPACE="AutoOps/Services"
export MONITORING_SERVICE_DIMENSION="ServiceName"
export MONITORING_ERROR_RATE_METRIC="ErrorRate"
export MONITORING_LATENCY_METRIC="Latency"
export MONITORING_ERROR_RATE_THRESHOLD="1.0"
export MONITORING_LATENCY_THRESHOLD_MS="500"
export CHECKPOINT_DB_PATH="autoops_checkpoints.db"
export CODEREVIEW_A2A_URL="http://localhost:9003"
export A2A_BEARER_TOKEN=""
```

`GITHUB_REPO` is optional if you run AutoOps from inside a GitHub repository known to the `gh` CLI.

## Usage

Run a natural-language task through the AutoOps graph:

```bash
python3 -m autoops.main "show health for checkout-service"
```

More examples:

```bash
python3 -m autoops.main "list open PRs"
python3 -m autoops.main "show logs for checkout-service"
python3 -m autoops.main "run a security scan on autoops"
python3 -m autoops.main "summarize the incident for checkout-service"
python3 -m autoops.main "create an issue for checkout-service high error rate"
```

If installed with `python3 -m pip install -e ".[dev]"`, you can also use the console command:

```bash
autoops "show health for checkout-service"
```

Write actions pause for approval in the terminal before execution. For example, creating a GitHub issue prompts for `yes`, `no`, or `show-full`.

## MCP Servers

Agents normally start their MCP servers over stdio automatically. You can also run each server directly:

```bash
python3 autoops/mcp/mcp_github.py
python3 autoops/mcp/mcp_cloudwatch.py
python3 autoops/mcp/mcp_codereview.py
python3 autoops/mcp/mcp_monitoring.py
```

To expose an MCP server over SSE, set `MCP_TRANSPORT=sse` and the relevant port variable:

```bash
MCP_TRANSPORT=sse GITHUB_MCP_PORT=8001 python3 autoops/mcp/mcp_github.py
MCP_TRANSPORT=sse CLOUDWATCH_MCP_PORT=8002 python3 autoops/mcp/mcp_cloudwatch.py
MCP_TRANSPORT=sse CODEREVIEW_MCP_PORT=8003 python3 autoops/mcp/mcp_codereview.py
MCP_TRANSPORT=sse MONITORING_MCP_PORT=8004 python3 autoops/mcp/mcp_monitoring.py
```

## A2A Code Review Server

The Code Review A2A server exposes:

- `GET /.well-known/agent.json`
- `POST /tasks`

Start the server:

```bash
uvicorn autoops.a2a.server:app --host 0.0.0.0 --port 9003
```

Then delegate compatible tasks such as `diff_summary`, `lint`, and `security_scan`.

## Testing

Run the test suite:

```bash
python3 -m pytest
```

Run a focused test file:

```bash
python3 -m pytest tests/unit/test_cloudwatch_agent.py
```

## Notes

- CloudWatch tools use the default boto3 credential chain.
- Monitoring tools read CloudWatch metrics, alarms, and deployment logs.
- Code review tools intentionally stay inside the project root when resolving paths.
- GitHub issue creation is treated as a write operation and requires human approval.
