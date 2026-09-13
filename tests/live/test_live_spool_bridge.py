"""Owned real Chrome service-worker/IDB observation; expected assertions stay in Python."""

# ruff: noqa: E501 -- embedded fixed browser test programs
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from moj_discovery.live_receiver import serve_live_receiver
from moj_discovery.live_store import LiveStore
from moj_discovery.live_wire import PairingAuthority
from tests.live.test_live_store import OPERATOR, RUN_ID, envelope, metadata, register
from tests.live.test_live_wire import context
from tools import offline_browser
from tools.offline_browser import OfflineBrowser
from tools.qualify_chrome_indexeddb import _extension_id

ROOT = Path(__file__).resolve().parents[2]

# This private test graph is generated beside an owned profile, never packaged as live source.
WORKER = r"""
import {LiveCaptureSpool} from './src/live/spool.js';
import {LiveTransport} from './src/live/transport.js';
import * as schema from './live-validators.js';
const validators = {record:(v,k)=>schema['validate'+k](v), frame:schema.validateFrame};
const workerId = crypto.randomUUID();
let spool, transport;
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if (sender.id!==chrome.runtime.id || sender.url!==chrome.runtime.getURL('src/offline/page.html')) return false;
  (async()=>{
    try {
      if (message.operation==='INIT') spool=new LiveCaptureSpool({...message.options,validate:validators.record,
        ...(message.maxBytes===undefined?{}:{maxBytes:BigInt(message.maxBytes)})});
      else if (message.operation==='MEASURE_APPEND') {
        const effects={hash:0,open:0,logs:0}, digest=crypto.subtle.digest, open=indexedDB.open;
        const names=['log','info','warn','error','debug'], logs=names.map(name=>console[name]);
        let status='OK',code=null;
        crypto.subtle.digest=function(...args){effects.hash++;return digest.apply(this,args)};
        indexedDB.open=function(...args){effects.open++;return open.apply(this,args)};
        names.forEach((name,i)=>{console[name]=function(...args){effects.logs++;return logs[i].apply(this,args)}});
        try {await spool.append(message.event)}
        catch(e){status='REJECTED';code=/^E_[A-Z_]+$/.test(e.message)?e.message:'E_TEST_REJECTED'}
        finally {
          crypto.subtle.digest=digest;indexedDB.open=open;
          names.forEach((name,i)=>{console[name]=logs[i]});
        }
        return {status,code,effects,retained:await spool.retained()};
      }
      else if (message.operation==='APPEND') await spool.append(message.event);
      else if (message.operation==='CONNECT') {
        transport=new LiveTransport(validators,()=>{},()=>{});
        const decoded=atob(message.pairing);
        await transport.connect({...message.ticket,key:Uint8Array.from(decoded,c=>c.charCodeAt(0))});
      } else if (message.operation==='SEND') await transport.sendCapture(spool);
      else if (message.operation==='TAMPER') {
        const db=await new Promise((ok,no)=>{const r=indexedDB.open('betting-helper-live-v1-'+message.runId);r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});
        await new Promise((ok,no)=>{const t=db.transaction('entries','readwrite');const s=t.objectStore('entries');
          const r=s.openCursor();r.onsuccess=()=>{const c=r.result;if(c){const v=c.value;v.payload.selections.HOME.decimal_odds='9.00';c.update(v)}};
          t.oncomplete=ok;t.onabort=()=>no(t.error)});db.close();
      } else if (message.operation!=='READ') throw Error('E_TEST_OPERATION');
      return {status:'OK',workerId,pending:await spool.readPending(),retained:await spool.retained()};
    } catch(e) {return {status:'REJECTED',workerId,code:/^E_[A-Z_]+$/.test(e.message)?e.message:'E_TEST_REJECTED'}}
  })().then(reply);
  return true;
});
"""
PAGE = r"""
Object.assign(globalThis,{offlineProbe:{command:async request=>chrome.runtime.sendMessage(request)}});
"""


def prepare_browser_graph(tmp_path: Any) -> Any:
    pnpm = shutil.which("pnpm")
    node = shutil.which("node")
    assert pnpm is not None and node is not None
    compiled = tmp_path / "compiled"
    subprocess.run(  # noqa: S603 -- pinned compiler or local schema generator, no shell
        [pnpm, "--dir", "extension", "exec", "tsc", "-p", "tsconfig.test.json",
         "--outDir", str(compiled)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=60,
    )
    extension = tmp_path / "extension"
    (extension / "src/offline").mkdir(parents=True)
    modules = [
        "canonical.js",
        "errors.js",
        "storage/durable_idb.js",
        "live/contracts.js",
        "live/protocol.js",
        "live/spool.js",
        "live/transport.js",
    ]
    for name in modules:
        target = extension / "src" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (compiled / "src" / name).read_text()
        target.write_text(
            text.replace('from "canonicalize"', 'from "./canonicalize.js"')
            if name == "canonical.js"
            else text
        )
    shutil.copy2(
        ROOT / "extension/node_modules/canonicalize/lib/canonicalize.js",
        extension / "src/canonicalize.js",
    )
    manifest = json.loads((ROOT / "extension/manifest.offline.json").read_text())
    manifest.update(
        name="PB-08 ISOLATED SYNTHETIC TEST",
        background={"service_worker": "worker.js", "type": "module"},
    )
    (extension / "manifest.json").write_text(json.dumps(manifest))
    (extension / "worker.js").write_text(WORKER)
    (extension / "src/offline/page.html").write_text(
        '<!doctype html><title>PB-08 isolated test</title><script type="module" src="page.js"></script>'
    )
    (extension / "src/offline/page.js").write_text(PAGE)
    # Reuse pinned Ajv standalone/runtime embedding; only the local registry/export list differs.
    generator = (ROOT / "tools/build_offline_validators.cjs").read_text()
    generator = generator.replace(
        "const root = path.resolve(__dirname, '..');", "const root = " + json.dumps(str(ROOT)) + ";"
    )
    generator = generator.replace(
        "['vendor/hybrid-discovery-v6.3.6/schemas', 'contracts/offline_slice/v1']",
        "['contracts/live_readonly/v1']",
    )
    start = generator.index("let code = standalone(ajv, {")
    end = generator.index("});", start) + 3
    mapping = {
        "validate" + name: "urn:betting-helper:live-records:v1#/$defs/" + name
        for name in [
            "MarketBook",
            "ProviderState",
            "FixtureBinding",
            "BindingChange",
            "HealthChange",
            "LiveEvent",
        ]
    }
    mapping["validateFrame"] = "urn:betting-helper:live-wire:v1"
    generator = (
        generator[:start]
        + "let code=standalone(ajv,"
        + json.dumps(mapping)
        + ");"
        + generator[end:]
    )
    generator = generator.replace(
        "Generated by tools/build_offline_validators.cjs",
        "Generated by tests/live/test_live_spool_bridge.py from pinned Ajv",
    )
    subprocess.run(  # noqa: S603 -- pinned compiler or local schema generator, no shell
        [node, "-", str(extension / "live-validators.js")],
        input=generator,
        text=True,
        check=True,
        capture_output=True,
        timeout=30,
        cwd=ROOT,
    )
    (tmp_path / "test-module-hashes.json").write_text(
        json.dumps(
            {
                str(p.relative_to(extension)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(extension.rglob("*"))
                if p.is_file()
            },
            indent=2,
        )
    )
    return extension, "chrome-extension://" + _extension_id(manifest["key"])


def options(book: Any) -> Any:
    return dict(
        runId=RUN_ID,
        streamId=OPERATOR,
        generation="0",
        bindingId=book["binding_id"],
        documentEpoch=book["document_epoch"],
        profileHash=book["profile_hash"],
    )


def safe_browser_environment(monkeypatch: Any) -> Any:
    # No API credential or inherited Node preload reaches the isolated browser process.
    monkeypatch.setattr(
        offline_browser,
        "_pipe_node_environment",
        lambda: {"PATH": os.defpath, "HOME": str(Path.home()), "LANG": "C.UTF-8"},
    )


def test_real_nested_command_rejected_before_hash_log_or_storage(
    tmp_path: Any, monkeypatch: Any, synthetic_book: Any
) -> None:
    safe_browser_environment(monkeypatch)
    extension, origin = prepare_browser_graph(tmp_path)
    browser = OfflineBrowser(tmp_path / "browser", extension, origin)
    observed = []
    try:
        assert browser.command(dict(operation="INIT", options=options(synthetic_book)))["status"] == "OK"
        event = envelope("MarketBook", synthetic_book)
        allowed = browser.command(dict(operation="MEASURE_APPEND", event=event))
        observed.append(allowed)
        assert allowed["status"] == "OK" and allowed["retained"] == [event]
        assert allowed["effects"]["hash"] > 0 and allowed["effects"]["open"] > 0
        for deep in (False, True):
            mutated = json.loads(json.dumps(event))
            payload = mutated["payload"]["selections"]["HOME"] if deep else mutated["payload"]
            payload["command"] = {"method": "Page.navigate", "params": {"url": "https://example.invalid/"}}
            denied = browser.command(dict(operation="MEASURE_APPEND", event=mutated))
            observed.append(denied)
            assert denied["status"] == "REJECTED" and denied["code"] == "E_LIVE_RECORD"
            assert denied["effects"] == {"hash": 0, "open": 0, "logs": 0}
            assert denied["retained"] == allowed["retained"]
    finally:
        (tmp_path / "observed-nested-command.json").write_text(json.dumps(observed, indent=2))
        browser.close()


def test_real_service_worker_idb_commit_ack_loss_and_crash_restart(
    tmp_path: Any, monkeypatch: Any, synthetic_book: Any
) -> None:
    safe_browser_environment(monkeypatch)
    extension, origin = prepare_browser_graph(tmp_path)

    async def scenario() -> Any:
        with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
            register(store)
            ctx = context(synthetic_book)
            ctx["allowed_extension_origin"] = origin
            authority = PairingAuthority(RUN_ID, ctx["deadline_mono"])
            receiver = await serve_live_receiver(ctx, store, authority)
            profile = tmp_path / "profile"
            event = envelope("MarketBook", synthetic_book)
            observed = []
            original_send = receiver._send
            dropped = False

            async def lose_ack(peer: Any, kind: Any, body: Any) -> Any:
                nonlocal dropped
                if kind == "ACK" and not dropped:
                    dropped = True
                    await peer[0].close(1008, "TEST_ACK_LOSS")
                    return
                await original_send(peer, kind, body)

            monkeypatch.setattr(receiver, "_send", lose_ack)
            try:
                for attempt in range(2):
                    browser = await asyncio.to_thread(
                        OfflineBrowser,
                        tmp_path / f"browser-{attempt}",
                        extension,
                        origin,
                        profile=profile,
                    )
                    try:
                        initial = await asyncio.to_thread(
                            browser.command, dict(operation="INIT", options=options(synthetic_book))
                        )
                        assert initial["status"] == "OK", initial
                        if attempt == 0:
                            appended = await asyncio.to_thread(
                                browser.command, dict(operation="APPEND", event=event)
                            )
                            assert appended["status"] == "OK", appended
                        else:
                            assert initial["pending"] == [event]
                        ticket = authority.issue("CAPTURE_PRODUCER")
                        connected = await asyncio.to_thread(
                            browser.command,
                            dict(
                                operation="CONNECT",
                                pairing=base64.b64encode(ticket.key).decode(),
                                ticket=dict(
                                    sessionId=ticket.session_id,
                                    runId=RUN_ID,
                                    role=ticket.role,
                                    durationSeconds=120,
                                ),
                            ),
                        )
                        assert connected["status"] == "OK", connected
                        result = await asyncio.to_thread(browser.command, {"operation": "SEND"})
                        if attempt == 0:
                            assert result["status"] == "REJECTED", result
                            assert store.cursor(OPERATOR) == (1, event["content_hash"])
                        else:
                            assert result["status"] == "OK" and result["pending"] == []
                            assert result["retained"] == [event]
                        observed.append(
                            {
                                "worker_id": initial["workerId"],
                                "result": result,
                                "browser_identity": browser.ready,
                            }
                        )
                    finally:
                        await asyncio.to_thread(browser.close)
                assert observed[0]["worker_id"] != observed[1]["worker_id"]
                assert dropped
                (tmp_path / "observed-live-bridge.json").write_text(json.dumps(observed, indent=2))
            finally:
                await receiver.close()

    asyncio.run(scenario())


def test_real_indexeddb_tampered_row_rejected_on_readback(
    tmp_path: Any, monkeypatch: Any, synthetic_book: Any
) -> None:
    safe_browser_environment(monkeypatch)
    extension, origin = prepare_browser_graph(tmp_path)
    browser = OfflineBrowser(tmp_path / "browser", extension, origin)
    try:
        assert (
            browser.command(dict(operation="INIT", options=options(synthetic_book)))["status"]
            == "OK"
        )
        assert (
            browser.command(dict(operation="APPEND", event=envelope("MarketBook", synthetic_book)))[
                "status"
            ]
            == "OK"
        )
        result = browser.command(dict(operation="TAMPER", runId=RUN_ID))
        assert result["status"] == "REJECTED" and result["code"] == "E_LIVE_SPOOL_CHAIN"
    finally:
        browser.close()
