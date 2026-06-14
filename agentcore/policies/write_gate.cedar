// AutoOps write gate policy.
// Write tools are allowed only after the AutoOps HITL checkpoint records approval.

permit (
  principal is AgentCore::Agent,
  action in [AgentCore::Action::"call_tool"],
  resource is AgentCore::Tool
)
when {
  resource.tool_type != "write" ||
  context.session.write_approved == true
};

forbid (
  principal is AgentCore::Agent,
  action in [AgentCore::Action::"call_tool"],
  resource is AgentCore::Tool
)
when {
  resource.tool_type == "write" &&
  context.session.write_approved != true
};
