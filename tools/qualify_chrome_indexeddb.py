"""Real local Chrome IndexedDB durability qualification."""
from __future__ import annotations

import argparse
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from signal import SIGKILL
from socket import socket
from subprocess import DEVNULL, PIPE, Popen, run
from threading import Thread
from time import monotonic, sleep
from urllib.request import urlopen


_SENTINEL = "HD636_INDEXEDDB_SENTINEL"
_CDP = r'''
const socket = new WebSocket(process.argv[1]);
const expression = process.argv[2];
let nextId = 1;
const pending = new Map();
const opened = new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});
socket.onmessage = event => {
  const message = JSON.parse(event.data);
  const resolve = pending.get(message.id);
  if (resolve) { pending.delete(message.id); resolve(message); }
};
const call = (method, params) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, resolve);
  socket.send(JSON.stringify({id, method, params}));
});
(async () => {
  await opened;
  const response = await call("Runtime.evaluate", {
    expression, awaitPromise: true, returnByValue: true
  });
  socket.close();
  if (response.error || response.result.exceptionDetails) {
    throw new Error(JSON.stringify(response));
  }
  process.stdout.write(JSON.stringify(response.result.result.value));
})().catch(error => { console.error(String(error)); process.exit(1); });
'''


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


def _free_port() -> int:
    with socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _wait_for_json(port: int, url: str) -> str:
    deadline = monotonic() + 15
    endpoint = f"http://127.0.0.1:{port}/json/list"
    while monotonic() < deadline:
        try:
            pages = json.loads(urlopen(endpoint, timeout=1).read())
            for page in pages:
                if page.get("type") == "page" and page.get("url") == url:
                    return str(page["webSocketDebuggerUrl"])
        except OSError:
            pass
        sleep(0.1)
    raise RuntimeError("E_CHROME_CDP_UNAVAILABLE")


def _start_chrome(profile: Path, url: str) -> tuple[Popen[bytes], str]:
    port = _free_port()
    process = Popen(
        [
            "google-chrome",
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            url,
        ],
        stdout=DEVNULL,
        stderr=DEVNULL,
        start_new_session=True,
    )
    try:
        return process, _wait_for_json(port, url)
    except Exception:
        _kill(process)
        raise


def _kill(process: Popen[bytes]) -> None:
    if process.poll() is None:
        os.killpg(process.pid, SIGKILL)
        process.wait(timeout=10)


def _evaluate(websocket_url: str, expression: str) -> object:
    completed = run(
        ["node", "-e", _CDP, websocket_url, expression],
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        check=False,
        timeout=20,
    )
    if completed.returncode:
        raise RuntimeError(f"E_CHROME_INDEXEDDB_EVALUATE:{completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _write_expression() -> str:
    return (
        "(async()=>{const db=await new Promise((ok,no)=>{const r=indexedDB.open('hd636',1);"
        "r.onupgradeneeded=()=>r.result.createObjectStore('v');r.onsuccess=()=>ok(r.result);"
        "r.onerror=()=>no(r.error)});await new Promise((ok,no)=>{const t=db.transaction('v','readwrite');"
        "t.objectStore('v').put('" + _SENTINEL + "','sentinel');t.oncomplete=ok;t.onerror=()=>no(t.error)});"
        "db.close();return '" + _SENTINEL + "'})()"
    )


def _read_expression() -> str:
    return (
        "(async()=>{const db=await new Promise((ok,no)=>{const r=indexedDB.open('hd636',1);"
        "r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});const value=await new Promise((ok,no)=>{"
        "const r=db.transaction('v').objectStore('v').get('sentinel');r.onsuccess=()=>ok(r.result);"
        "r.onerror=()=>no(r.error)});db.close();return value})()"
    )


def qualify_chrome_indexeddb_environment(workspace: Path) -> dict[str, object]:
    """Persist a sentinel in a real browser, SIGKILL it, then read after restart."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "index.html").write_text("<!doctype html><title>HD636</title>")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_QuietHandler, directory=str(workspace))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/index.html"
    profile = workspace / "chrome-profile"
    first: Popen[bytes] | None = None
    second: Popen[bytes] | None = None
    try:
        first, websocket_url = _start_chrome(profile, url)
        written = _evaluate(websocket_url, _write_expression())
        if written != _SENTINEL:
            raise RuntimeError("E_CHROME_INDEXEDDB_WRITE")
        _kill(first)
        first = None
        second, websocket_url = _start_chrome(profile, url)
        durable = _evaluate(websocket_url, _read_expression())
        if durable != _SENTINEL:
            raise RuntimeError("E_CHROME_INDEXEDDB_DURABILITY")
        return {
            "result": "PASS",
            "browser_process": "google-chrome",
            "abrupt_kill": True,
            "durable_sentinel": durable,
        }
    finally:
        if first is not None:
            _kill(first)
        if second is not None:
            _kill(second)
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify_chrome_indexeddb_environment(args.workspace), sort_keys=True))


if __name__ == "__main__":
    main()
