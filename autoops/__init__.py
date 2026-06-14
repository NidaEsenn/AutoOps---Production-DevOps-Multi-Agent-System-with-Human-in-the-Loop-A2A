"""AutoOps package."""

from dotenv import load_dotenv

# Load environment variables from a local .env file (if present) on import.
# This runs for the CLI, the API wrapper, and any stdio-spawned MCP servers
# (they inherit os.environ via os.environ.copy()). Existing environment
# variables always take precedence over .env values.
load_dotenv(override=False)

# Initialise Logfire (no-op unless LOGFIRE_TOKEN or AUTOOPS_LOGFIRE_CONSOLE set).
# Runs after load_dotenv so it can read observability settings from .env.
from autoops.observability import configure_observability  # noqa: E402

configure_observability()

