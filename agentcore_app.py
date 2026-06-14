"""Root-level AgentCore entrypoint for AutoOps.

The real app lives in `autoops/agentcore_app.py`. This thin wrapper sits at the
repo root on purpose: the AgentCore runtime puts the entrypoint file's directory
on sys.path, and if that directory were `autoops/`, our `autoops/mcp/` package
would shadow the installed `mcp` SDK (ImportError: cannot import ClientSession).
Keeping the entrypoint at the repo root means sys.path[0] is the repo root, so
`mcp` resolves to the SDK and `autoops.mcp` to our subpackage.
"""

import os

from autoops.agentcore_app import app, invoke  # noqa: F401  (re-exported for the runtime)

if __name__ == "__main__":
    app.run(port=int(os.getenv("AGENTCORE_PORT", "8080")))
