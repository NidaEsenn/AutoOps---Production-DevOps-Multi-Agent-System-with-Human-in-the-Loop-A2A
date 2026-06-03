"""CLI entry point for AutoOps."""

import argparse
import asyncio
import json

from autoops.hitl import run_with_approval_loop
from autoops.state import initial_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an AutoOps task.")
    parser.add_argument("task", help="Natural-language DevOps task to run.")
    parser.add_argument(
        "--session-id",
        default="local-dev",
        help="Session id used for state continuity and future checkpointing.",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    state = initial_state(args.task, session_id=args.session_id)
    final_state = await run_with_approval_loop(state)

    print("AutoOps run complete")
    print(f"Active agent: {final_state['active_agent']}")
    print(json.dumps(final_state["agent_outputs"], indent=2))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
