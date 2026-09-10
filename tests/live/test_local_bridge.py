"""Actual selected browser/WSL path; synthetic fixture oracle stays in Python."""

# ruff: noqa: E501 -- Fixed isolated test programs.
import asyncio
import base64
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.live.test_live_service import make_service
from tests.live.test_live_spool_bridge import safe_browser_environment
from tools import offline_browser
from tools.qualify_live_platform import CHROME, ROOT, WindowsBrowser, build_live_extension, hashes

PAGE = r"""
const panes={};
const wait=()=>new Promise(r=>setTimeout(r,300));
function open(){for(const name of ['panel','workspace']){const f=document.createElement('iframe');
 f.src='../live/'+name+'.html';document.body.append(f);panes[name]=f;}}
open();
const observe=()=>Object.fromEntries(Object.entries(panes).map(([k,f])=>[k,{
 text:f.contentDocument.body.textContent,revision:f.contentDocument.querySelector('section')?.dataset.revision,
 input:f.contentDocument.querySelector('input')?.value}]));
globalThis.offlineProbe={command:async m=>{
 if(m.operation==='CLOSE_PANELS'){for(const [k,f] of Object.entries(panes)){f.remove();delete panes[k];}return {status:'OK',observed:observe()};}
 if(m.operation==='OPEN_PANELS')open();
 if(m.operation==='WRONG_PATH'){return {status:'OK',observed:await new Promise(ok=>{let opened=false;const w=new WebSocket('ws://127.0.0.1:8765/wrong');w.onopen=()=>{opened=true;w.close()};w.onclose=()=>ok({opened});})};}
 for(let i=0;i<60 && !panes.panel?.contentDocument?.querySelector('input');i++)await wait();
 if(m.operation==='PAIR'){const d=panes.panel.contentDocument;d.querySelector('input').value=m.ticket;d.querySelector('form').requestSubmit();}
 else if(!['OBSERVE','OPEN_PANELS'].includes(m.operation))throw Error('E_TEST_OPERATION');
 await wait();return {status:'OK',observed:observe()};
}};
"""


def private_driver(output: Path) -> Path:
    driver = (ROOT / "tools/chrome_pipe.cjs").read_text()
    driver = "const pb15Versions=new Map(),pb15History=[];\n" + driver
    needle = "const value = JSON.parse(raw), waiter = pending.get(value.id);"
    assert needle in driver
    driver = driver.replace(
        needle,
        needle
        + "\nif(value.method==='ServiceWorker.workerVersionUpdated')for(const v of value.params.versions){pb15Versions.set(v.versionId,v);pb15History.push(v);}",
    )
    needle = "let document;"
    driver = driver.replace(
        needle, "await call('ServiceWorker.enable',{},attached.sessionId);\n" + needle
    )
    needle = "const task = evaluate(attached.sessionId, expression, true).then(result => {"
    assert needle in driver
    driver = driver.replace(
        needle,
        """const task = (async()=>{
      if(request.operation==='PB15_STOP_WORKER'){
        const workers=[...pb15Versions.values()].filter(v=>v.scriptURL===config.origin+'/src/live/background.js'&&v.runningStatus==='running');
        if(workers.length!==1)throw Error('E_TEST_WORKER_IDENTITY');
        for(const v of workers)await call('ServiceWorker.stopWorker',{versionId:v.versionId},attached.sessionId,true);
        await new Promise(r=>setTimeout(r,500));
        return {status:'OK',observed:{before:workers,after:pb15History}};
      }
      return await evaluate(attached.sessionId,expression,true);
    })().then(result => {""",
    )
    (output / "tools").mkdir(parents=True)
    path = output / "tools/chrome_pipe.cjs"
    path.write_text(driver)
    return path


def test_actual_selected_platform_bridge_and_worker_repair(
    tmp_path: Path,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    selected = os.environ.get("PB_PLATFORM", "WINDOWS_CHROME_WSL2")
    assert selected in {"WINDOWS_CHROME_WSL2", "LINUX_CHROME"}
    extension, origin = build_live_extension(tmp_path / "build")
    production_hashes = hashes(extension)
    assert "export " not in (extension / "src/live/dom_reader.js").read_text()
    assert not any("offline" in name or "test" in name for name in production_hashes)
    assert "validateRaw" not in (extension / "live-validators.js").read_text()
    # Private page is added only after binding the production graph.
    (extension / "src/offline").mkdir()
    (extension / "src/offline/page.html").write_text(
        '<!doctype html><title>PB-15 isolated synthetic</title><script type="module" src="page.js"></script>'
    )
    (extension / "src/offline/page.js").write_text(PAGE)
    driver = private_driver(tmp_path / "driver")
    service, http, book, _ = make_service(
        tmp_path / "service",
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )
    service.admitted = replace(service.admitted, extension_origin=origin)
    service._receiver_context["allowed_extension_origin"] = origin
    observations = []
    browser: Any = None

    def ticket() -> str:
        result: dict[str, Any] = {
            "version": 1,
            "runId": service.admitted.run_id,
            "durationSeconds": 120,
        }
        for name, role in (("ui", "UI_SUBSCRIBER"), ("capture", "CAPTURE_PRODUCER")):
            pair = service.pairing.issue(role)
            result[name] = {
                "sessionId": pair.session_id,
                "key": base64.urlsafe_b64encode(pair.key).decode().rstrip("="),
            }
        return json.dumps(result)

    async def scenario() -> None:
        nonlocal browser
        try:
            await service.start()
            await service.tick()
            server = service.receiver.server
            assert server is not None
            addresses = sorted({s.getsockname()[0] for s in server.sockets})
            assert addresses == ["127.0.0.1"]
            safe_browser_environment(monkeypatch)
            if selected == "WINDOWS_CHROME_WSL2":
                browser = await asyncio.to_thread(WindowsBrowser, extension, origin, driver)
            else:
                with monkeypatch.context() as scoped:
                    scoped.setattr(offline_browser, "ROOT", driver.parent.parent)
                    browser = await asyncio.to_thread(
                        offline_browser.OfflineBrowser, tmp_path / "browser", extension, origin
                    )

            async def command(operation: str, **values: Any) -> Any:
                result = await asyncio.to_thread(
                    browser.command, {"operation": operation, **values}
                )
                observations.append({"operation": operation, "result": result})
                assert result["status"] == "OK"
                return result["observed"]

            async def paired() -> Any:
                seen = await command("PAIR", ticket=ticket())
                for _ in range(20):
                    if all("CONNECTED" in v["text"] and v.get("revision") for v in seen.values()):
                        return seen
                    seen = await command("OBSERVE")
                raise AssertionError("Actual Chrome did not receive authenticated WSL projection")

            first = await paired()
            assert first["panel"]["revision"] == first["workspace"]["revision"]
            assert all(v["input"] == "" for v in first.values())
            assert service.receiver.connected("CAPTURE_PRODUCER")
            assert await command("WRONG_PATH") == {"opened": False}
            count = len(http.paths)
            assert await command("CLOSE_PANELS") == {}
            assert service.receiver.connected("UI_SUBSCRIBER")
            await command("OPEN_PANELS")
            assert len(http.paths) == count
            stopped = await command("PB15_STOP_WORKER")
            version = stopped["before"][0]["versionId"]
            assert any(
                v["versionId"] == version and v["runningStatus"] == "stopped"
                for v in stopped["after"]
            )
            for _ in range(20):
                if not service.receiver.connected("CAPTURE_PRODUCER"):
                    break
                await asyncio.sleep(0.1)
            assert not service.receiver.connected("CAPTURE_PRODUCER")
            assert service.view(book["binding_id"])["market_eligible"] is False
            repaired = await paired()
            assert repaired["panel"]["revision"] == repaired["workspace"]["revision"]
            assert len(http.paths) == count
            local = await command("OBSERVE")
            assert all(
                "SYNTHETIC" in v["text"] and "MODEL_NOT_QUALIFIED" in v["text"]
                for v in local.values()
            )
            (tmp_path / "observed-bridge.json").write_text(
                json.dumps(
                    {
                        "platform": selected,
                        "bound_addresses": addresses,
                        "extension_origin": origin,
                        "browser_identity": browser.ready,
                        "browser_workspace": str(browser.workspace),
                        "browser_sha256": hashlib.sha256(
                            (
                                CHROME
                                if selected == "WINDOWS_CHROME_WSL2"
                                else Path("/opt/google/chrome/chrome")
                            ).read_bytes()
                        ).hexdigest(),
                        "source_kind": "SYNTHETIC",
                        "operator_observed": False,
                        "real_provider_attempts": 0,
                        "mock_attempts": count,
                        "observations": observations,
                        "production_build_hashes": production_hashes,
                        "sleep_wake": "NOT_OBSERVED",
                        "physical_power_loss": "NOT_OBSERVED",
                        "native_side_panel_toolbar": "NOT_OBSERVED",
                    },
                    indent=2,
                )
            )
        finally:
            if browser is not None:
                await asyncio.to_thread(browser.close)
            await service.close("USER_STOP")

    asyncio.run(scenario())
    assert browser is not None
    termination = json.loads((browser.workspace / "termination.json").read_text())
    (tmp_path / "observed-termination.json").write_text(json.dumps(termination, indent=2))
    if selected == "WINDOWS_CHROME_WSL2":
        assert termination["all_observed_handles_signaled"]
