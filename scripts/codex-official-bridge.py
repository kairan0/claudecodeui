#!/usr/bin/env python3
"""CloudCLI IPC adapter for the unchanged, pinned Codex 0.166 Python SDK.

The SDK owns the child, native wire IO and response correlation. CloudCLI owns
notifications and asynchronous approvals. The private SDK hooks and process
handle used here are version-pinned and covered by subprocess contract tests.
"""
import json
import signal
import subprocess
import sys
import threading

from openai_codex.client import CodexClient, CodexConfig
from openai_codex.errors import JsonRpcError


class BridgeClient(CodexClient):
    def __init__(self, command):
        super().__init__(CodexConfig(launch_args_override=tuple(command)),
                         approval_handler=self.reject_fallback)
        self.finished = threading.Event()
        self.failed = False
        self.output_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending_approvals = set()
        self.requests = threading.BoundedSemaphore(128)

    @staticmethod
    def reject_fallback(_method, _params):
        raise RuntimeError("Approvals must be answered by CloudCLI")

    def emit(self, message):
        with self.output_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def _read_message(self):
        # Never block the sole SDK reader waiting for a human. Forward requests
        # with their native ids; responses still pass through the SDK router.
        try:
            while True:
                message = super()._read_message()
                if "method" not in message:
                    return message
                if "id" in message:
                    with self.pending_lock:
                        self.pending_approvals.add(message["id"])
                self.emit(message)
        except BaseException:
            if not self.finished.is_set():
                self.failed = True
                self.finished.set()
            raise

    def call(self, message):
        try:
            result = self._request_raw(message["method"], message.get("params"))
            self.emit({"id": message["id"], "result": result})
        except JsonRpcError as error:
            self.emit({"id": message["id"], "error": {
                "code": error.code, "message": error.message, "data": error.data}})
        except Exception:
            # A native IO failure invalidates every run, not just this RPC.
            # Exit so Node settles all runs; never expose SDK stderr tails.
            self.failed = True
            self.finished.set()
        finally:
            self.requests.release()

    def read_parent(self):
        try:
            for line in sys.stdin:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Expected an IPC object")
                if "method" in message:
                    if "id" not in message:
                        self.notify(message["method"], message.get("params"))
                    elif self.requests.acquire(blocking=False):
                        threading.Thread(target=self.call, args=(message,), daemon=True).start()
                    else:
                        self.emit({"id": message["id"], "error": {
                            "code": -32000, "message": "Too many pending Codex requests"}})
                else:
                    # Forward only answers to requests the native server made.
                    with self.pending_lock:
                        self.pending_approvals.remove(message["id"])
                    response = {"id": message["id"]}
                    if "error" in message:
                        response["error"] = message["error"]
                    else:
                        response["result"] = message["result"]
                    self._write_message(response)
        except Exception:
            self.failed = True
            print("CloudCLI official client IPC failed", file=sys.stderr)
        finally:
            self.finished.set()

    def close(self):
        # SDK close() first closes buffered stdin. If a writer is blocked on a
        # full native pipe, that close waits on its buffer lock. A watchdog must
        # be able to terminate the engine without acquiring any IO locks.
        proc = self._proc
        closed = threading.Event()

        def force_exit():
            if proc is None or closed.wait(0.5):
                return
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass

        watchdog = threading.Thread(target=force_exit, daemon=True)
        watchdog.start()
        try:
            super().close()
        except BrokenPipeError:
            # The SDK may raise before reaching terminate(). The watchdog
            # remains armed until the native child has actually been reaped.
            pass
        finally:
            if proc is not None:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            closed.set()
            watchdog.join(timeout=3)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Expected the Codex app-server launch command")
    client = BridgeClient(sys.argv[1:])
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_args: client.finished.set())
    try:
        client.start()
        threading.Thread(target=client.read_parent, daemon=True).start()
        client.finished.wait()
    finally:
        client.close()
    return 1 if client.failed else 0


if __name__ == "__main__":
    sys.exit(main())
