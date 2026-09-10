# ruff: noqa: E501 -- Fixed private browser driver programs.
import asyncio
import base64
import copy
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.live_contracts import event_hash, schema_validate
from moj_discovery.live_state import capture_observation_id
from moj_discovery.live_wire import validate_frame
from moj_discovery.workspace_projection import project_watchlist
from tests.live.test_live_service import make_service
from tests.live.test_live_spool_bridge import prepare_browser_graph, safe_browser_environment
from tests.live.test_live_store import envelope
from tools import offline_browser


def test_empty_workspace_keeps_unknown_source_time_and_models_disabled() -> None:
    view = project_watchlist(
        {
            "run_id": None,
            "views": [],
            "selected": [],
            "max_matches": 1,
            "source_kind": "MOCK",
            "quota": {
                "session_remaining": 600,
                "daily_remaining": 6000,
                "minute_remaining": 6,
                "provider_remaining": None,
            },
            "provider_connection": "WAITING",
            "capture_connection": "DISCONNECTED",
        }
    )
    assert view["model_status"] == "MODEL_NOT_QUALIFIED"
    assert view["money_ready"] is False
    assert view["matches"] == [] and view["source_time_status"] == "UNKNOWN"


ROOT = Path(__file__).resolve().parents[2]


def test_persisted_projection_revision_budget_and_closed_wire(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    service, _, book, _ = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )

    async def scenario() -> None:
        try:
            await service.start()
            await service.tick()
            snapshot = service.snapshot()
            view = snapshot["workspace"]["matches"][0]
            body = service.wire_projection(book["binding_id"])
            assert (
                body["revision"]
                == view["revision"]
                == str(snapshot["views"][0]["projection_revision"])
            )
            assert body["display"]["source_age_us"] is None
            assert body["display"]["quota"]["session_remaining"] == 598
            assert body["capture_scope"]["profile_status"] == "DRAFT"
            frame = dict(
                protocol="BH_LIVE_WIRE_V1",
                session_id=service.admitted.run_id,
                direction="BACKEND_TO_CLIENT",
                counter="1",
                message_type="PROJECTION",
                body=body,
                mac="0" * 64,
            )
            schema_validate(frame, "wire")
            validate_frame(frame)
            for key, value in [("source_age_us", 0), ("unknown_field", True), ("max_matches", 20)]:
                changed = copy.deepcopy(frame)
                changed["body"]["display"][key] = value
                with pytest.raises(ValueError):
                    validate_frame(changed)
            changed = copy.deepcopy(frame)
            changed["body"]["capture_scope"]["exact_url"] += "/wrong"
            with pytest.raises(ValueError):
                validate_frame(changed)
            for key, value in [
                ("max_matches", 20),
                ("selected", ["unknown"]),
                ("source_kind", "LIVE"),
            ]:
                changed = copy.deepcopy(snapshot)
                changed[key] = value
                with pytest.raises(ValueError):
                    project_watchlist(changed)
            view["binding"]["home_name"] = "changed outside store"
            assert (
                service.view(book["binding_id"])["binding"]["home_name"] != "changed outside store"
            )
        finally:
            await service.close("USER_STOP")

    asyncio.run(scenario())


# Private synthetic driver: actual packaged UI pages and worker, no production commands added.
PAGE = r"""
const panes={};
for(const name of ['panel','workspace']) {
 const frame=document.createElement('iframe');frame.src='../live/'+name+'.html';
 frame.style.cssText='width:320px;height:900px;border:0';document.body.append(frame);panes[name]=frame;
}
const wait=()=>new Promise(r=>setTimeout(r,250));
const doc=n=>panes[n].contentDocument;
const observe=()=>Object.fromEntries(Object.keys(panes).map(n=>{
 const d=doc(n);return [n,{text:d.body.textContent,buttons:[...d.querySelectorAll('button')].map(b=>({text:b.textContent,disabled:b.disabled})),
  viewportWidth:d.defaultView.innerWidth,htmlNodes:d.querySelectorAll('img,svg').length,width:d.documentElement.clientWidth,scrollWidth:d.documentElement.scrollWidth,
  revision:d.querySelector('section').dataset.revision,binding:d.querySelector('section').dataset.binding,
  navRevision:d.querySelector('nav [aria-current=true]')?.dataset.revision,
  focus:d.activeElement?.textContent,expanded:d.querySelector('details')?.open,input:d.querySelector('input').value}]}));
globalThis.offlineProbe={command:async m=>{
 for(let i=0;i<80 && !doc('panel')?.querySelector('section');i++) await wait();
 if(m.operation==='INTENT') return {status:'OK',observed:(await chrome.storage.local.get('liveWatchlistIntent')).liveWatchlistIntent};
 if(m.operation==='PAIR') {doc('panel').querySelector('input').value=m.ticket;doc('panel').querySelector('form').requestSubmit();await wait();}
 else if(m.operation==='HORIZON') doc('panel').querySelector('[data-horizon="'+m.horizon+'"]').click();
 else if(m.operation==='OTHER') {const {renderMatch}=await import('../live/panel.js');renderMatch(m.projection,'FT',doc('panel').querySelector('section'));}
 else if(m.operation==='FOCUS') doc('panel').querySelector('[data-horizon="FT"]').focus();
 else if(m.operation==='EVIDENCE') {const s=doc('panel').querySelector('summary');s.click();s.focus();}
 else if(m.operation==='CLICK') {const b=[...doc('panel').querySelectorAll('button')].find(b=>b.textContent===m.label);b.click();await wait();}
 else if(m.operation==='REOPEN') {panes.panel.src=panes.panel.src;await wait();}
 else if(m.operation==='WAIT') await new Promise(r=>setTimeout(r,1200));
 else if(m.operation!=='OBSERVE') throw Error('E_TEST_OPERATION');
 return {status:'OK',observed:observe()};
}};
"""


def test_actual_chrome_panel_shared_worker_keyboard_and_narrow_layout(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    extension, origin = prepare_browser_graph(tmp_path)
    for name in ("background", "capture", "panel", "workspace"):
        shutil.copy2(
            ROOT / f"extension/.test-build/src/live/{name}.js", extension / f"src/live/{name}.js"
        )
    for name in ("panel.html", "workspace.html", "panel.css"):
        shutil.copy2(ROOT / "extension/src/live" / name, extension / "src/live" / name)
    background = extension / "src/live/background.js"
    background.write_text(
        "import * as schema from '../../live-validators.js';\n"
        + background.read_text()
        + "\nstartLiveWorkspace({record:(v,k)=>schema['validate'+k](v),frame:schema.validateFrame});\n"
    )
    (extension / "manifest.json").write_bytes((ROOT / "extension/manifest.live.json").read_bytes())
    (extension / "src/offline/page.js").write_text(PAGE)
    (tmp_path / "graph-hashes.json").write_text(
        json.dumps(
            {
                str(p.relative_to(extension)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in extension.rglob("*")
                if p.is_file()
            },
            indent=2,
        )
    )
    # The private pipe adds exactly Tab/Enter and a screenshot operation for this owned test.
    # It is not shipped in the extension or installed into the existing browser helper.
    driver = (ROOT / "tools/chrome_pipe.cjs").read_text()
    marker = "const task = evaluate(attached.sessionId, expression, true).then(result => {"
    assert marker in driver
    driver = driver.replace(
        marker,
        """const task = (async()=>{
      if(request.operation==='PB13_TAB' || request.operation==='PB13_ENTER') {
        const key=request.operation==='PB13_TAB'?'Tab':'Enter',code=key==='Tab'?9:13;
        await call('Input.dispatchKeyEvent',{type:'keyDown',key,code:key,windowsVirtualKeyCode:code},attached.sessionId,true);
        if(key==='Enter') await call('Input.dispatchKeyEvent',{type:'char',text:String.fromCharCode(13),key,code:key,windowsVirtualKeyCode:code},attached.sessionId,true);
        await call('Input.dispatchKeyEvent',{type:'keyUp',key,code:key,windowsVirtualKeyCode:code},attached.sessionId,true);
        return await evaluate(attached.sessionId,'globalThis.offlineProbe.command({operation:"OBSERVE"})',true);
      }
      if(request.operation==='PB13_SCREENSHOT') {
        const shot=await call('Page.captureScreenshot',{format:'png'},attached.sessionId,true);
        fs.writeFileSync(path.join(directory,'panel.png'),Buffer.from(shot.data,'base64'));
        return {status:'OK',screenshot:'panel.png'};
      }
      return await evaluate(attached.sessionId,expression,true);
    })().then(result => {""",
    )
    driver_root = tmp_path / "driver"
    (driver_root / "tools").mkdir(parents=True)
    (driver_root / "tools/chrome_pipe.cjs").write_text(driver)
    service, http, book, stream = make_service(
        tmp_path / "service",
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )
    service.admitted = replace(service.admitted, extension_origin=origin)
    service._receiver_context["allowed_extension_origin"] = origin
    outputs = []

    async def scenario() -> None:
        browser = None
        try:
            await service.start()
            await service.tick()
            ticket: dict[str, Any] = {
                "version": 1,
                "runId": service.admitted.run_id,
                "durationSeconds": 120,
            }
            for key, role in (("ui", "UI_SUBSCRIBER"), ("capture", "CAPTURE_PRODUCER")):
                item = service.pairing.issue(role)
                ticket[key] = {
                    "sessionId": item.session_id,
                    "key": base64.urlsafe_b64encode(item.key).decode().rstrip("="),
                }
            safe_browser_environment(monkeypatch)
            with monkeypatch.context() as isolated:
                isolated.setattr(offline_browser, "ROOT", driver_root)
                browser = await asyncio.to_thread(
                    offline_browser.OfflineBrowser, tmp_path / "browser", extension, origin
                )

            async def command(operation: str, **values: Any) -> Any:
                result = await asyncio.to_thread(
                    browser.command, {"operation": operation, **values}
                )
                outputs.append(result)
                assert result["status"] == "OK"
                return result.get("observed")

            observed = await command("PAIR", ticket=json.dumps(ticket))
            for _ in range(12):
                if "CONNECTED" in observed["panel"]["text"] and observed["panel"]["revision"]:
                    break
                observed = await command("WAIT")
            assert service.receiver.connected("UI_SUBSCRIBER") and service.receiver.connected(
                "CAPTURE_PRODUCER"
            )
            challenge = await service.request_capture(book["binding_id"])
            event = envelope("MarketBook", book, stream=stream)
            event.update(
                run_id=service.admitted.run_id,
                observation_id=capture_observation_id(challenge, "FT"),
            )
            event["content_hash"] = event_hash(event)
            service.store.append(event)
            await service.capture_received(event)
            body = service.wire_projection(book["binding_id"])
            body["binding"]["home_name"] = '<img src=x onerror="alert(1)">'
            (tmp_path / "synthetic-projection-oracle.json").write_text(json.dumps(body, indent=2))
            await service.receiver.publish(body)
            observed = await command("WAIT")
            for pane in observed.values():
                assert "MODEL_NOT_QUALIFIED" in pane["text"] and "SYNTHETIC" in pane["text"]
                assert '<img src=x onerror="alert(1)">' in pane["text"] and pane["htmlNodes"] == 0
                assert pane["viewportWidth"] == 320 and pane["scrollWidth"] <= pane["width"]
                assert pane["revision"] == pane["navRevision"] == body["revision"]
                assert pane["input"] == ""
                assert not any(
                    b["text"].lower() in {"bet", "cashout", "buy", "sell"} for b in pane["buttons"]
                )
                assert next(b for b in pane["buttons"] if b["text"] == "Open LiveScore match")[
                    "disabled"
                ]
            assert observed["panel"]["revision"] == observed["workspace"]["revision"]
            await command("FOCUS")
            observed = await command("PB13_TAB")
            assert observed["panel"]["focus"] == "H1"
            observed = await command("PB13_ENTER")
            assert "H1: NO_DATA" in observed["panel"]["text"]
            assert book["selections"]["HOME"]["decimal_odds"] not in observed["panel"]["text"]
            other = copy.deepcopy(body)
            other["binding"]["binding_id"] = "99999999-9999-4999-8999-999999999999"
            other["binding"]["home_name"] = "SYNTHETIC OTHER"
            # Old A book intentionally accompanies B: renderer must not display A prices.
            observed = await command("OTHER", projection=other)
            assert (
                "SYNTHETIC OTHER" in observed["panel"]["text"]
                and "FT: NO_DATA" in observed["panel"]["text"]
            )
            assert book["selections"]["HOME"]["decimal_odds"] not in observed["panel"]["text"]
            await command("HORIZON", horizon="FT")
            await command("PB13_SCREENSHOT")
            await command("EVIDENCE")
            observed = await command("WAIT")
            assert (
                observed["panel"]["expanded"] and observed["panel"]["focus"] == "Show data evidence"
            )
            observed = await command("REOPEN")
            assert (
                observed["panel"]["revision"] == observed["workspace"]["revision"]
                and len(http.paths) == 2
            )
            await command("CLICK", label="Pause / Remove fixture")
            observed = await command("WAIT")
            assert (
                "PAUSED" in observed["panel"]["text"] and "PAUSED" in observed["workspace"]["text"]
            )
            assert book["selections"]["HOME"]["decimal_odds"] in observed["panel"]["text"]
            assert len(http.paths) == 2
            intent = await command("INTENT")
            assert intent["active"] == book["binding_id"]
            assert intent["bindings"] == [
                {"bindingId": book["binding_id"], "profileHash": book["profile_hash"]}
            ]
            await command("CLICK", label="Stop session")
            await command("WAIT")
            assert service._reason == "USER_STOP"
        finally:
            if browser is not None:
                browser.close()
            await service.close("USER_STOP")
            (tmp_path / "actual-browser-observations.json").write_text(
                json.dumps(outputs, indent=2)
            )

    asyncio.run(scenario())
