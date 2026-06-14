"""Test isolation: keep the suite hermetic and offline.

A developer's local .env (loaded on `import autoops`) may enable the LLM
router, LangSmith tracing, or Logfire. Tests must not depend on those — they
should exercise the deterministic keyword routing with no network calls.

We pre-set these variables to disabled values here, at conftest import time
(before any test imports `autoops`). Because the package uses
`load_dotenv(override=False)`, these pre-set values win over .env, so the suite
stays hermetic regardless of the developer's local .env.
"""

import os

_DISABLED_ENV = {
    "GROQ_API_KEY": "",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGCHAIN_API_KEY": "",
    "LANGSMITH_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "LANGSMITH_WORKSPACE_ID": "",
    "LOGFIRE_TOKEN": "",
    "AUTOOPS_LOGFIRE_CONSOLE": "false",
}

for _var, _value in _DISABLED_ENV.items():
    os.environ[_var] = _value
