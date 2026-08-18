"""Unit tests for tracing.py's no-op behavior.

These tests run in this project's normal dev environment, which has no
LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY set (see .env) — that's exactly
the "no Langfuse account yet" case the no-op path exists for. Confirms
the decorators are true identity wrappers in that case (not just
functionally inert but actually the same function object), and that
decorated functions still run and return correctly.
"""

import asyncio

import tracing


def test_langfuse_is_disabled_in_this_dev_environment():
    """Sanity check the premise of every other test in this file: no
    keys are configured, so we're exercising the no-op path."""
    assert tracing._LANGFUSE_ENABLED is False


def test_traced_agent_is_true_identity_decorator():
    def func(x):
        return x + 1

    wrapped = tracing.traced_agent("some_agent")(func)
    assert wrapped is func  # not just "behaves the same" -- the literal same object


def test_traced_decision_is_true_identity_decorator():
    def func(x):
        return x * 2

    wrapped = tracing.traced_decision("some_decision")(func)
    assert wrapped is func


def test_traced_tool_is_true_identity_decorator():
    def func(x):
        return x - 1

    wrapped = tracing.traced_tool("some_tool")(func)
    assert wrapped is func


def test_traced_decorators_do_not_break_async_functions():
    @tracing.traced_agent("async_agent")
    async def async_func(x):
        return x * 10

    result = asyncio.run(async_func(4))
    assert result == 40
