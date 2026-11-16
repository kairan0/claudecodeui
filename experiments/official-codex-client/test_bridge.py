"""Exercise the bridge as a child process, including the real pinned CLI."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest
from app_server_harness import AppServerHarness
from app_server_helpers import streaming_response

ROOT = Path(__file__).resolve().parents[2]


class Peer:
    def __init__(self, command, env=None, cwd=None):
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/codex-official-bridge.py"), *command],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={**os.environ, **(env or {})}, cwd=cwd,
        )
        self.messages = queue.Queue()
        self.saved = []
        self.backlog = []
        self.next_id = 0
        def read():
            for line in self.proc.stdout:
                self.messages.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def receive(self, predicate):
        for index, message in enumerate(self.backlog):
            if predicate(message):
                return self.backlog.pop(index)
        while True:
            message = self.messages.get(timeout=8)
            self.saved.append(message)
            if predicate(message):
                return message
            self.backlog.append(message)

    def call(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params or {}})
        response = self.receive(lambda m: m.get("id") == request_id and "method" not in m)
        assert "error" not in response, response
        return response["result"]

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
                raise
        self.proc.stdout.close()
        self.proc.stderr.close()


@pytest.mark.parametrize("ending", ["stdin", "signal", "native_eof"])
def test_approval_does_not_block_other_sessions_or_control_and_shutdown_reaps_child(tmp_path, ending):
    # Native fixture sends a request and deliberately withholds an answer.
    fixture = tmp_path / "native.py"
    fixture.write_text('''import json, os, sys, time
def emit(m):
    print(json.dumps(m), flush=True)
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "fixture/approval":
        emit({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {"threadId": "a"}})
    elif m.get("method") == "fixture/eof":
        os.close(1)
        time.sleep(30)
    elif "method" in m:
        emit({"id": m["id"], "result": {"pid": os.getpid()}})
    else:
        emit({"method": "fixture/answer", "params": m})
''')
    peer = Peer([sys.executable, "-u", str(fixture)])
    try:
        pid = peer.call("initialize")["pid"]
        peer.send({"method": "fixture/approval"})
        approval = peer.receive(lambda m: m.get("id") == "approval-1")
        assert approval["method"] == "item/commandExecution/requestApproval"
        # This would hang if we installed a blocking SDK approval handler.
        peer.call("turn/interrupt", {"threadId": "b", "turnId": "other"})
        assert not any(m.get("method") == "fixture/answer" for m in peer.saved)
        peer.send({"id": "approval-1", "result": {"decision": "decline"}})
        answer = peer.receive(lambda m: m.get("method") == "fixture/answer")
        assert answer["params"]["result"] == {"decision": "decline"}
        if ending == "signal":
            peer.proc.terminate()
        elif ending == "native_eof":
            peer.send({"method": "fixture/eof"})
        else:
            peer.proc.stdin.close()
        peer.proc.wait(timeout=5)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert peer.proc.returncode == (1 if ending == "native_eof" else 0)
    finally:
        peer.close()


def test_real_codex_steer_and_resume_native_history(tmp_path):
    with AppServerHarness(tmp_path) as harness:
        harness.responses.enqueue_sse(
            streaming_response("first", "message-first", ["before steer"]),
            delay_between_events_s=0.2,
        )
        harness.responses.enqueue_assistant_message("after steer", response_id="second")
        config = harness.app_server_config()
        peer = Peer([config.codex_bin, "app-server", "--listen", "stdio://"], config.env, config.cwd)
        try:
            peer.call("initialize", {"clientInfo": {"name": "cloudcli-test", "version": "0.166.0"},
                                     "capabilities": {"experimentalApi": True}})
            peer.send({"method": "initialized"})
            thread = peer.call("thread/start", {"config": {"features.instant_interrupt": False}})["thread"]["id"]
            turn = peer.call("turn/start", {"threadId": thread,
                "input": [{"type": "text", "text": "Start a steerable turn."}]})["turn"]["id"]
            harness.responses.wait_for_requests(1)
            result = peer.call("turn/steer", {"threadId": thread, "expectedTurnId": turn,
                "input": [{"type": "text", "text": "Use this steering input."}]})
            assert result["turnId"] == turn
            terminal = peer.receive(lambda m: m.get("method") == "turn/completed")
            assert terminal["params"]["turn"]["status"] == "completed"
            history = peer.call("thread/read", {"threadId": thread, "includeTurns": True})
            assert "after steer" in json.dumps(history)
        finally:
            peer.close()

        # A new bridge reads the same native store, without importing a snapshot.
        peer = Peer([config.codex_bin, "app-server", "--listen", "stdio://"], config.env, config.cwd)
        try:
            peer.call("initialize", {"clientInfo": {"name": "cloudcli-test", "version": "0.166.0"}})
            peer.send({"method": "initialized"})
            history = peer.call("thread/read", {"threadId": thread, "includeTurns": True})
            assert "after steer" in json.dumps(history)
            # This client only reads while another client continues the
            # disposable thread. Reading again must not return a cached snapshot.
            harness.responses.enqueue_assistant_message("external update", response_id="third")
            external = Peer([config.codex_bin, "app-server", "--listen", "stdio://"], config.env, config.cwd)
            try:
                external.call("initialize", {"clientInfo": {"name": "external-test", "version": "0.166.0"}})
                external.send({"method": "initialized"})
                external.call("thread/resume", {"threadId": thread})
                external.call("turn/start", {"threadId": thread,
                    "input": [{"type": "text", "text": "Continue in another client."}]})
                external.receive(lambda m: m.get("method") == "turn/completed")
            finally:
                external.close()
            history = peer.call("thread/read", {"threadId": thread, "includeTurns": True})
            assert "external update" in json.dumps(history)
        finally:
            peer.close()


@pytest.mark.parametrize("failure", ["blocked_write", "broken_pipe"])
def test_native_write_failure_cannot_leave_an_orphan_engine(tmp_path, failure):
    fixture = tmp_path / "stalled.py"
    fixture.write_text('''import json, os, signal, sys, time
def emit(m):
    print(json.dumps(m), flush=True)
m = json.loads(sys.stdin.readline())
if sys.argv[1] == "broken_pipe":
    os.close(0)
else:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
emit({"method": "fixture/ready"})
emit({"id": m["id"], "result": {"pid": os.getpid()}})
if sys.argv[1] != "broken_pipe":
    os.read(0, 1)
    emit({"method": "fixture/stalled"})
time.sleep(60)
''')
    peer = Peer([sys.executable, "-u", str(fixture), failure])
    try:
        pid = peer.call("initialize")["pid"]
        peer.receive(lambda m: m.get("method") == "fixture/ready")
        peer.send({"id": 10, "method": "turn/start", "params": {"text": "x" * 1_000_000}})
        if failure == "blocked_write":
            peer.receive(lambda m: m.get("method") == "fixture/stalled")
            peer.proc.stdin.close()
        # broken_pipe must terminate without a parent shutdown request.
        peer.proc.wait(timeout=5)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        if failure == "broken_pipe":
            assert peer.proc.returncode == 1
    finally:
        peer.close()


def test_cloudcli_runtime_uses_official_bridge_for_same_turn_steer(tmp_path):
    with AppServerHarness(tmp_path) as harness:
        harness.responses.enqueue_sse(
            streaming_response("runtime-first", "runtime-message", ["before steer"]),
            delay_between_events_s=0.3,
        )
        harness.responses.enqueue_assistant_message("after steer", response_id="runtime-second")
        config = harness.app_server_config()
        result = subprocess.run(
            ["node", "--import", str(ROOT / "node_modules/tsx/dist/loader.mjs"),
             str(Path(__file__).with_name("runtime_fixture.mjs"))],
            env={**os.environ, **config.env,
                 "DATABASE_PATH": str(tmp_path / "cloudcli.db"),
                 "TSX_TSCONFIG_PATH": str(ROOT / "server/tsconfig.json"),
                 "CLOUDCLI_CODEX_PYTHON": sys.executable,
                 "CLOUDCLI_CODEX_BRIDGE_SCRIPT": str(ROOT / "scripts/codex-official-bridge.py")},
            cwd=config.cwd, text=True, capture_output=True, timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "CLOUDCLI_RUNTIME_BRIDGE_OK" in result.stdout
        requests = harness.responses.wait_for_requests(2)
        assert requests[-1].message_input_texts("user")[-1] == "Use this steering input."
