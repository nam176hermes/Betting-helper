"""Actual isolated Chrome observations, with faults confined to the private test graph."""

# ruff: noqa: E501 -- fixed private browser programs
import hashlib
import json
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from moj_discovery.live_contracts import validate_live_record
from moj_discovery.operator_profile import ProfileEvidence, validate_extraction_profile
from tests.live.test_live_spool_bridge import prepare_browser_graph, safe_browser_environment
from tests.live.test_live_store import binding
from tests.live.test_operator_profile import profile, sample
from tools.offline_browser import OfflineBrowser

ROOT = Path(__file__).resolve().parents[2]
WORKER = r"""
import {startReadOnlyCapture as testStartReadOnlyCapture, takeDiscoverySample, runDiscoveryTicket as testRunDiscoveryTicket} from './capture.js';
let capture, tabId, senderObservation;
const books=[], notices=[];
chrome.runtime.onMessage.addListener((m,s,reply)=>{
 if(s.id!==chrome.runtime.id || s.url!==chrome.runtime.getURL('src/offline/page.html')) return false;
 (async()=>{try {
  if(m.operation==='START') {
   if(capture) await capture.stop();
   const tab=await chrome.tabs.create({url:m.plan.exactUrl,active:true});tabId=tab.id;
   for(let n=0;n<100 && (await chrome.tabs.get(tabId)).status!=='complete';n++) await new Promise(r=>setTimeout(r,50));
   await chrome.scripting.executeScript({target:{tabId,frameIds:[0]},files:['test-sender.js'],world:'ISOLATED'});
   senderObservation=await chrome.tabs.sendMessage(tabId,{kind:'PB10_TEST_SENDER'});
   capture=await testStartReadOnlyCapture({...m.plan,tabId},{onBook:async(b,c)=>{books.push({book:b,challenge:c})},onInvalidation:c=>notices.push(c),onRecapture:()=>notices.push('RECAPTURE')});
  } else if(m.operation==='DISCOVERY_TICKET') {
   await capture.stop();
   await new Promise(r=>setTimeout(r,2100));
   await testRunDiscoveryTicket(m.ticket,tabId);
   return {status:'OK'};
  } else if(m.operation==='DISCOVERY') {
   await capture.stop();
   await new Promise(r=>setTimeout(r,2100));
   const p=m.plan;
   const sample=await takeDiscoverySample({tabId,exactUrl:p.exactUrl,sourceKind:'SYNTHETIC_TEST',
     fieldMapHash:p.profileHash,expiresAt:p.expiresAt,leaseMs:600000,
     selectors:{...p.selectors,home_id:null,away_id:null}});
   return {status:'OK',sample};
  } else if(m.operation==='READ') {await capture.request(m.challenge);}
  else if(m.operation==='FAULT') {
   if(!['hidden','missing','secret','unstable','root','route','context','swapped'].includes(m.fault)) throw Error();
   await chrome.scripting.executeScript({target:{tabId,frameIds:[0]},files:['test-'+m.fault+'.js'],world:'ISOLATED'});
   await new Promise(r=>setTimeout(r,350));
  } else if(m.operation==='HIDE') {await chrome.tabs.create({url:'about:blank',active:true});await new Promise(r=>setTimeout(r,100));}
  else if(m.operation==='WAIT_WATCHDOG') {await new Promise(r=>setTimeout(r,30100));}
  else if(m.operation==='STOP') {await capture.stop();}
  else if(m.operation!=='OBSERVE') throw Error();
  return {status:'OK',books,notices,identity:capture?.identity,senderObservation};
 }catch{return {status:'REJECTED',books,notices,senderObservation}}})().then(reply);return true;
});
"""
FAULTS = {
    "hidden": "document.querySelector('#draw-odds').style.display='none';",
    "missing": "document.querySelector('#draw-selection').remove();",
    "secret": "const n=document.createElement('input');n.type='password';n.value='TEST_ONLY_INNER_SECRET';document.querySelector('#home-odds').append(n);",
    "unstable": "let n=0;setInterval(()=>{document.querySelector('#home-odds').textContent=String(2+(++n)/1000)},20);",
    "root": "const r=document.querySelector('#TEST_ONLY_MATCH');r.replaceWith(r.cloneNode(true));",
    "route": "history.pushState({},'', '/match/replaced');",
    "context": "document.querySelector('#score').textContent='ambiguous';document.querySelector('#period').textContent='unknown label';",
    "swapped": "document.querySelector('#home-id').textContent='SYNTHETIC-A';",
}


def make_graph(tmp_path: Any) -> Any:
    extension, origin = prepare_browser_graph(tmp_path)
    compiler = shutil.which("pnpm")
    assert compiler is not None
    subprocess.run(  # noqa: S603 -- pinned compiler, separate private classic-script output
        [
            compiler,
            "--dir",
            "extension",
            "exec",
            "tsc",
            "-p",
            "tsconfig.test.json",
            "--moduleDetection",
            "legacy",
            "--outDir",
            str(tmp_path / "classic"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=60,
    )
    hashes = {}
    for name in ("dom_reader", "capture", "background", "panel"):
        source = tmp_path / "classic/src/live" / (name + ".js")
        destination = extension / "src/live" / (name + ".js")
        destination.write_bytes(source.read_bytes())
        hashes[str(destination.relative_to(extension))] = hashlib.sha256(
            source.read_bytes()
        ).hexdigest()
    manifest = json.loads((ROOT / "extension/manifest.live.json").read_text())
    manifest["host_permissions"] = ["http://127.0.0.1/*"]
    manifest["optional_host_permissions"] = []
    (extension / "manifest.json").write_text(json.dumps(manifest))
    (extension / "src/live/panel.html").write_text("<!doctype html><title>PB10 TEST ONLY</title>")
    background = extension / "src/live/background.js"
    background.write_text(background.read_text() + WORKER)
    (extension / "test-sender.js").write_text(
        "chrome.runtime.onMessage.addListener((m,s,r)=>{if(m.kind==='PB10_TEST_SENDER'){r({id:s.id,url:s.url??null,tabId:s.tab?.id??null});}return false;});"
    )
    for name, text in FAULTS.items():
        (extension / ("test-" + name + ".js")).write_text(text)
    (tmp_path / "capture-source-modules.json").write_text(json.dumps(hashes, indent=2))
    (tmp_path / "capture-test-graph.json").write_text(
        json.dumps(
            {
                str(p.relative_to(extension)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(extension.rglob("*"))
                if p.is_file()
            },
            indent=2,
        )
    )
    return extension, origin


def make_plan(tmp_path: Any, port: int) -> Any:
    p = profile()
    p["origin"] = f"http://127.0.0.1:{port}"
    b = binding()
    # The loopback HTML is a test navigation target, not an admitted FixtureBinding URL.
    # The synthetic oracle remains separate from the browser observations below.
    now = datetime.now(UTC)
    draft = validate_extraction_profile(p, ProfileEvidence(tmp_path, now))
    markets = sample(p)["markets"]
    (tmp_path / "synthetic-capture-oracle.json").write_text(
        json.dumps({"profile": p, "markets": markets})
    )

    return dict(
        tabId=0,
        exactUrl=p["origin"] + "/match/101",
        sourceKind="SYNTHETIC_TEST",
        profileStatus="DRAFT",
        profileHash=draft.profile_hash,
        expiresAt=(now + timedelta(minutes=10)).isoformat(),
        leaseMs=600000,
        bindingId=b["binding_id"],
        bindingRevision=b["revision"],
        operatorFixtureId=b["operator_fixture_id"],
        homeId=b["operator_home_id"],
        awayId=b["operator_away_id"],
        documentEpoch=str(uuid4()),
        clockDomainId=str(uuid4()),
        captureRevision="0",
        priceParser=p["price_parser"],
        selectors=p["selectors"],
        markets=markets,
    )


def discovery_wire_observation(browser: Any, plan: Any, origin: str) -> Any:
    """SYNTHETIC peer, actual isolated Chrome reader and WebSocket crypto exchange."""
    import asyncio
    import base64

    from websockets.asyncio.server import serve

    from moj_discovery.live_intent import discovery_mac, validate_discovery_sample

    key, run_id, nonce = b"D" * 32, str(uuid4()), "a" * 64
    assert len(key) == 32
    ready = threading.Event()
    actual, failures = [], []
    p = dict(
        exactUrl=plan["exactUrl"],
        sourceKind="SYNTHETIC_TEST",
        fieldMapHash=plan["profileHash"],
        expiresAt=plan["expiresAt"],
        leaseMs=10000,
        selectors={**plan["selectors"], "home_id": None, "away_id": None},
    )

    async def peer() -> None:
        done = asyncio.Event()

        async def exchange(ws: Any) -> None:
            try:
                await ws.send(json.dumps({"run_id": run_id, "nonce": nonce}))
                auth = json.loads(await ws.recv())
                assert auth == {"mac": discovery_mac(key, "AUTH", run_id, nonce)}
                payload = json.dumps(p)
                await ws.send(
                    json.dumps(
                        {
                            "payload": payload,
                            "mac": discovery_mac(key, "PLAN", run_id, nonce, payload),
                        }
                    )
                )
                frame = json.loads(await ws.recv())
                assert frame["mac"] == discovery_mac(key, "SAMPLE", run_id, nonce, frame["payload"])
                sample = json.loads(frame["payload"])
                validate_discovery_sample(sample, p)
                actual.append(sample)
                payload = json.dumps({"status": "UNADMITTED_SAMPLE_SAVED"})
                await ws.send(
                    json.dumps(
                        {
                            "payload": payload,
                            "mac": discovery_mac(key, "ACK", run_id, nonce, payload),
                        }
                    )
                )
            except Exception as exc:
                failures.append(type(exc).__name__)
            finally:
                done.set()

        async with serve(exchange, "127.0.0.1", 8765, origins=[origin], max_size=16384):
            ready.set()
            await asyncio.wait_for(done.wait(), 15)

    def run() -> None:
        try:
            asyncio.run(peer())
        except Exception as exc:
            failures.append(type(exc).__name__)
            ready.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert ready.wait(5) and not failures, failures
    ticket = json.dumps(
        dict(
            kind="OPERATOR_DISCOVERY",
            runId=run_id,
            key=base64.urlsafe_b64encode(key).decode().rstrip("="),
        )
    )
    result = browser.command(dict(operation="DISCOVERY_TICKET", ticket=ticket))
    worker.join(timeout=20)
    assert not worker.is_alive() and not failures and result["status"] == "OK", (failures, result)
    assert len(actual) == 1
    assert actual[0]["fields"]["draw_odds"] == "3.20"
    assert actual[0]["source_kind"] == "SYNTHETIC_TEST" and actual[0]["profile_accepted"] is False
    return actual[0]


def test_real_fixed_dom_complete_book_and_rejections(tmp_path: Any, monkeypatch: Any) -> None:
    safe_browser_environment(monkeypatch)
    html = (ROOT / "tests/live/fixtures/synthetic-match.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- stdlib callback
            if self.path != "/match/101":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    extension, origin = make_graph(tmp_path)
    browser = OfflineBrowser(tmp_path / "browser", extension, origin)
    plan = make_plan(tmp_path, server.server_port)
    observations = []
    try:
        for fault in (None, *FAULTS, "HIDE"):
            started = browser.command(dict(operation="START", plan=plan))
            assert started["status"] == "OK", started
            assert started["senderObservation"] == {
                "id": origin.removeprefix("chrome-extension://"),
                "url": origin + "/src/live/background.js",
                "tabId": None,
            }
            before = len(started["books"])
            if fault:
                damaged = browser.command(
                    dict(operation="HIDE")
                    if fault == "HIDE"
                    else dict(operation="FAULT", fault=fault)
                )
                assert damaged["status"] == "OK", damaged
            observed = browser.command(dict(operation="READ", challenge="a" * 64))
            observations.append({"fault": fault, "observed": observed})
            if fault in {None, "context"}:
                assert len(observed["books"]) == before + 1, observed
                book = observed["books"][-1]["book"]
                validate_live_record(book, "MarketBook")
                assert {side: q["decimal_odds"] for side, q in book["selections"].items()} == {
                    "HOME": "2.10",
                    "DRAW": "3.20",
                    "AWAY": "3.40",
                }
                assert book["source_updated_at"] is None and book["native_revision"] is None
                assert book["capture_evidence_tier"] == "DISPLAY_COHERENT"
                assert book["operator_score"] == (None if fault else {"home": 0, "away": 0})
                assert book["operator_period"] == (None if fault else "H1")
                # An immediate second read cannot emit another complete snapshot.
                again = browser.command(dict(operation="READ", challenge="b" * 64))
                assert len(again["books"]) == before + 1
                if fault is None:
                    waiting = browser.command(dict(operation="WAIT_WATCHDOG"))
                    assert waiting["notices"].count("RECAPTURE") > again["notices"].count(
                        "RECAPTURE"
                    )
                    recaptured = browser.command(dict(operation="READ", challenge="c" * 64))
                    assert len(recaptured["books"]) == before + 2
                    assert recaptured["books"][-1]["book"]["source_updated_at"] is None
                    observations.append({"watchdog_visible": recaptured})
            else:
                assert len(observed["books"]) == before, observed
            if fault == "HIDE":
                waiting = browser.command(dict(operation="WAIT_WATCHDOG"))
                assert waiting["notices"].count("RECAPTURE") == observed["notices"].count(
                    "RECAPTURE"
                )
                assert len(waiting["books"]) == before
                observations.append({"watchdog_hidden": waiting})
            assert "TEST_ONLY_INNER_SECRET" not in json.dumps(observed)
            assert "TEST_ONLY_EXCLUSION_CANARY" not in json.dumps(observed)
            if fault in {None, "missing", "secret", "HIDE"}:
                discovery = browser.command(dict(operation="DISCOVERY", plan=plan))
                observations.append({"discovery_fault": fault, "observed": discovery})
                if fault == "HIDE":
                    assert discovery["status"] == "REJECTED"
                else:
                    assert discovery["status"] == "OK", discovery
                    candidate = discovery["sample"]
                    assert candidate["status"] == "UNADMITTED_SAMPLE"
                    assert candidate["source_kind"] == "SYNTHETIC_TEST"
                    assert candidate["profile_accepted"] is False
                    assert candidate["binding_verified"] is False
                    assert candidate["fields"]["home_id"] is None
                    assert candidate["fields"]["away_id"] is None
                    assert candidate["fields"]["home_odds"] == (
                        None if fault == "secret" else "2.10"
                    )
                    assert candidate["fields"]["draw_selection"] == (
                        None if fault == "missing" else "SYNTHETIC-DRAW"
                    )
                assert "TEST_ONLY_INNER_SECRET" not in json.dumps(discovery)
                assert "TEST_ONLY_EXCLUSION_CANARY" not in json.dumps(discovery)
                if fault is None:
                    observations.append(
                        {"discovery_wire": discovery_wire_observation(browser, plan, origin)}
                    )
        (tmp_path / "observed-capture.json").write_text(json.dumps(observations, indent=2))
    finally:
        browser.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_graph_has_fixed_injection_and_no_mutation_capability() -> None:
    manifest = json.loads((ROOT / "extension/manifest.live.json").read_text())
    assert manifest["permissions"] == ["storage", "sidePanel", "scripting", "activeTab"]
    assert not manifest["host_permissions"]
    assert manifest["optional_host_permissions"] == ["https://miseojeuplus.espacejeux.com/*"]
    reader = (ROOT / "extension/src/live/dom_reader.ts").read_text()
    capture = (ROOT / "extension/src/live/capture.ts").read_text()
    background = (ROOT / "extension/src/live/background.ts").read_text()
    graph = reader + capture + background
    for forbidden in (
        ".click(",
        "fetch(",
        "XMLHttpRequest",
        "document.cookie",
        "localStorage",
        "outerHTML",
        "innerHTML",
        "eval(",
        "new Function",
        "chrome.debugger",
        "chrome.cookies",
        "chrome.webRequest",
        "nativeMessaging",
        "Runtime.",
        "Input.",
    ):
        assert forbidden not in graph
    assert 'files: ["src/live/dom_reader.js"], world: "ISOLATED"' in capture
    assert "frameIds: [0]" in capture and "func:" not in capture
    assert "import " not in reader and "export " not in reader
    assert "chrome.permissions.request" not in graph  # PB13 owns the explicit user gesture.
    # Only this closed module edge is allowed; source changes require this graph check to change.
    import re

    for source, expected in [
        (capture, {"./contracts.js", "./background.js", "../canonical.js"}),
        (
            background,
            {
                "./capture.js",
                "./contracts.js",
                "./spool.js",
                "./transport.js",
                "./protocol.js",
                "../canonical.js",
                "./panel.js",
            },
        ),
    ]:
        assert set(re.findall(r'from "([^"]+)"', source)) == expected
