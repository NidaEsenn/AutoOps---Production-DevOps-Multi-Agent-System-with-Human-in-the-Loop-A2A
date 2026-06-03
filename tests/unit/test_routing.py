from autoops.supervisor import decide_route


def test_routes_github_prompt() -> None:
    decision = decide_route("list open PRs")

    assert decision.next_agent == "github"
    assert decision.reasoning
    assert decision.sub_task == "list open PRs"


def test_routes_cloudwatch_prompt() -> None:
    decision = decide_route("error rate on checkout-service spiked")

    assert decision.next_agent == "cloudwatch"


def test_routes_code_review_prompt() -> None:
    decision = decide_route("run security scan on this repo")

    assert decision.next_agent == "codereview"


def test_routes_monitoring_prompt() -> None:
    decision = decide_route("show service health for checkout-service")

    assert decision.next_agent == "monitoring"


def test_ambiguous_prompt_routes_to_end() -> None:
    decision = decide_route("help me think about lunch")

    assert decision.next_agent == "end"
