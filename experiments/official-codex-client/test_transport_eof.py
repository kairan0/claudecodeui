"""Check the prior CloudCLI EOF failure against unchanged official client code."""

import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from openai_codex.api import TurnHandle
from openai_codex.client import CodexClient, CodexConfig
from openai_codex.errors import TransportClosedError


def test_live_child_stdout_eof_releases_turn_subscriber():
    # Deliberately keep the child alive after stdout EOF: waiting for process
    # exit alone was insufficient in the original PR's transport adapter.
    fake = "import os, sys, time; sys.stdin.readline(); os.close(1); time.sleep(30)"
    client = CodexClient(
        CodexConfig(launch_args_override=(sys.executable, "-u", "-c", fake)),
        approval_handler=lambda _method, _params: {"decision": "decline"},
    )
    client.start()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        handle = TurnHandle(client, "fixture-thread", "fixture-turn")
        result = executor.submit(lambda: list(handle.stream()))
        client.notify("fixture/close-stdout")
        with pytest.raises(TransportClosedError, match="closed stdout"):
            result.result(timeout=3)
    finally:
        client.close()
        executor.shutdown(wait=True, cancel_futures=True)
