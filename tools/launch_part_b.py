"""Vietnamese user-terminal workflow; source actions retain their own gates."""

# ruff: noqa: E402
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WSL_RUNTIME = "/home/thenam176/betting-helper/part-b-candidate"
WINDOWS_RUNTIME = r"\\wsl.localhost\Ubuntu\home\thenam176\betting-helper\part-b-candidate"
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def public_input(prompt: str) -> str:
    if sys.platform == "win32":
        if not sys.stdin.isatty():
            raise ValueError("E_LAUNCHER_NO_CONSOLE")
        print(prompt, flush=True)
        return sys.stdin.readline(2049).strip()
    from moj_discovery.secrets_local import controlling_tty

    with controlling_tty() as terminal:
        terminal.write(prompt + "\n")
        terminal.flush()
        return terminal.readline(2049).strip()


def local_config_path(value: str) -> Path:
    from moj_discovery.live_config import private_path

    if not value.endswith(".json") or not value.startswith(".local/part-b/"):
        raise ValueError("E_LAUNCHER_CONFIG_PATH")
    return private_path(value, root=ROOT, must_exist=True)


def fixture_config(
    original: dict[str, Any], league: int, season: int, fixture: int
) -> dict[str, Any]:
    if (
        any(type(n) is not int or not 1 <= n <= 2147483647 for n in (league, season, fixture))
        or not 2000 <= season <= 2100
    ):
        raise ValueError("E_LAUNCHER_FIXTURE")
    value = copy.deepcopy(original)
    value["enabled"] = False
    value["provider"].update(league_id=league, season=season, fixture_ids=[fixture])
    value["runtime"].update(
        max_matches=1, max_run_minutes=min(120, value["runtime"]["max_run_minutes"])
    )
    value["operator"].update(
        allowed_fixture_bindings=[], capture_profile_path=None, profile_evidence_hash=None
    )
    for name in (
        "provider_feasibility_path",
        "capture_review_path",
        "security_review_path",
        "live_intent_path",
    ):
        value["gates"][name] = None
    return value


def save_json(path: Path, value: Any, *, replace: bool = False) -> None:
    if path.resolve() != path or (path.exists() and path.stat().st_nlink != 1):
        raise ValueError("E_LAUNCHER_PATH")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + str(uuid4()) + ".tmp") if replace else path
    with temporary.open("x") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        temporary.replace(path)


def key_metadata() -> dict[str, Any]:
    from moj_discovery.windows_credential_store import NATIVE_PYTHON, helper_command

    digest = hashlib.sha256(NATIVE_PYTHON.read_bytes()).hexdigest()
    command = helper_command("metadata", native_python_sha256=digest)
    result = subprocess.run(command, capture_output=True, env={}, timeout=15, check=False)  # noqa: S603 -- fixed helper metadata only.
    value = json.loads(result.stdout)
    if value == {"state": "ABSENT", "generation": None}:
        raise ValueError("ABSENT")
    if value == {"state": "IN_USE", "generation": None}:
        raise ValueError("IN_USE")
    if (
        result.returncode != 0
        or set(value) != {"state", "generation"}
        or value["state"] != "STORED"
    ):
        raise ValueError("WAITING_FOR_USER_SECRET")
    return {
        "backend": "WINDOWS_CREDENTIAL_MANAGER",
        "generation": value["generation"],
        "native_python_sha256": digest,
    }


def readiness(path: Path) -> bool:
    from dataclasses import asdict

    from moj_discovery.live_config import load_live_config
    from moj_discovery.live_preflight_batched import evaluate_live_readiness, load_evidence

    config = load_live_config(path)
    state = "NOT_CHECKED"
    try:
        configured = config.public.get("credentials")
        actual = key_metadata() if configured else None
        state = (
            "STORED"
            if configured and actual == configured
            else "ROTATED"
            if actual
            else "NOT_CHECKED"
        )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        state = str(error) if str(error) in {"ABSENT", "IN_USE"} else "UNAVAILABLE"
    present = None if state in {"NOT_CHECKED", "UNAVAILABLE"} else state == "STORED"
    evidence = load_evidence(config)
    result = evaluate_live_readiness(config, evidence, key_present=present)
    print("Cấu hình đang dùng: " + str(path))
    print("CONFIG_SHA256: " + config.sha256)
    print("SOURCE_SHA256: " + evidence.source_sha256)
    print("Kho key: " + state + "; chưa kiểm tra xác thực với provider")
    print("Fixture: " + ", ".join(map(str, config.fixture_ids)))
    print(
        "Giới hạn cấu hình: "
        + str(config.public["runtime"]["max_run_minutes"])
        + " phút / "
        + str(config.public["provider"]["max_requests_per_run"])
        + " lần gọi"
    )
    for name, value in asdict(result).items():
        if name != "live_read_only_ready":
            print(name + ": " + json.dumps(value, ensure_ascii=False))
    print("LIVE_READY: " + str(result.live_read_only_ready).lower())
    return result.live_read_only_ready


def prepare_live_intent(path: Path, config: Any, relative: str) -> bool:
    from moj_discovery.live_config import private_path
    from moj_discovery.live_intent import intent_is_consumed, load_run_intent
    from moj_discovery.live_preflight_batched import load_evidence
    from tools.prepare_part_b_intent import main as prepare

    target = private_path(relative, root=ROOT)
    evidence = load_evidence(config)
    if "capture" not in evidence.checks:
        print("WAITING_OPERATOR_SAMPLE: chưa có binding đã review cho trận này.")
        return False
    bindings = {b["provider_fixture_id"]: b for b in evidence.bindings}
    if set(bindings) != set(config.fixture_ids):
        raise ValueError("E_LAUNCHER_BINDING")
    urls = [bindings[fixture]["operator_match_url"] for fixture in config.fixture_ids]
    if target.exists():
        try:
            intent = load_run_intent(target, config, "LIVE_READ_ONLY", root=ROOT)
            if not intent_is_consumed(intent) and intent.public["operator_urls"] == urls:
                return True
        except ValueError:
            pass
        if (
            public_input(
                "Xác nhận cũ đã dùng hoặc hết hiệu lực. Gõ NEW LIVE INTENT để tạo phạm vi mới "
                "và giữ lại bản cũ; bước này chưa cho phép gọi API."
            )
            != "NEW LIVE INTENT"
        ):
            return False
        target = private_path(relative, root=ROOT, must_exist=True)
        target.rename(target.with_name(target.stem + ".archived-" + str(uuid4()) + ".json"))
    arguments = ["--stage", "live-readonly", "--config", str(path), "--output", relative]
    for url in urls:
        arguments.extend(["--operator-url", url])
    return prepare(arguments) == 0


def run_action(path: Path, action: str) -> int:
    from moj_discovery.live_config import load_live_config
    from tools.prepare_part_b_intent import main as prepare
    from tools.run_with_api_football_key import main as launch

    config = load_live_config(path)
    if "credentials" not in config.public:
        print("WAITING_FOR_USER_SECRET: quay về menu Windows, chọn Lưu API key một lần.")
        return 2
    if action == "live-readonly":
        if not readiness(path):
            return 2
        relative = config.public["gates"]["live_intent_path"]
        if relative is None:
            print("WAITING_REVIEW: cấu hình đã review cần có đường dẫn intent riêng.")
            return 2
        if not prepare_live_intent(path, config, relative):
            return 2
    else:
        relative = ".local/part-b/intents/probe-" + str(uuid4()) + ".json"
        if prepare(["--stage", "provider-probe", "--config", str(path), "--output", relative]) != 0:
            return 2
    return launch(["--action", action, "--config", str(path), "--intent", relative])


def windows_menu() -> int:
    record = delivered_package()
    runtime = Path(WINDOWS_RUNTIME)
    helper = runtime / "tools/windows_credential_helper.py"
    while True:
        print("Candidate: " + record["source_commit"])
        choice = public_input(
            "\nBETTING HELPER — CHỈ ĐỌC\n1. Mở ứng dụng / tiếp tục\n"
            "2. Lưu hoặc thay API key một lần\n3. Xóa API key đã lưu\n0. Thoát"
        )
        if choice == "0":
            return 0
        verify_credential_programs(record, runtime)
        if choice == "1":
            command = [
                r"C:\Windows\System32\wsl.exe",
                "-d",
                "Ubuntu",
                "--cd",
                WSL_RUNTIME,
                "--exec",
                WSL_RUNTIME + "/.venv/bin/python",
                "-B",
                "tools/launch_part_b.py",
                "--wsl",
                record["source_commit"],
                record["source_tree_sha256"],
            ]
        elif choice in {"2", "3"}:
            if choice == "2":
                print(
                    "Lấy key tại API-Football Account → My Access. "
                    "Chỉ nhập ở dòng ẩn trong terminal; không gửi key qua chat."
                )
            command = [
                sys.executable,
                "-I",
                "-B",
                str(helper),
                "--enroll" if choice == "2" else "--delete",
            ]
        else:
            continue
        subprocess.run(command, check=False)  # noqa: S603 -- fixed user-selected local actions, inherited user console.


def delivered_package() -> dict[str, Any]:
    import importlib.util

    path = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("part_b_package", path / "package_part_b.py")
    if spec is None or spec.loader is None:
        raise ValueError("E_DELIVERY_INTEGRITY")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(dict[str, Any], module.validate_delivery(path))


def verify_credential_programs(record: dict[str, Any], runtime: Path) -> None:
    names = {
        "tools/windows_credential_helper.py",
        "tools/launch_part_b.py",
        "src/moj_discovery/windows_credential_store.py",
        "src/moj_discovery/secrets_local.py",
    }
    if (
        set(record["backend_credential_files"]) != names
        or hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        != record["native_python_sha256"]
    ):
        raise ValueError("E_DELIVERY_BACKEND_CHANGED")
    for name, digest in record["backend_credential_files"].items():
        path = runtime / name
        if path.resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("E_DELIVERY_BACKEND_CHANGED")


def install_windows() -> int:
    record = delivered_package()
    source = Path(__file__).resolve().parent
    destination = Path.home() / "Documents/BettingHelper" / record["source_commit"][:12]
    shortcut = Path.home() / "Desktop" / ("Betting Helper " + record["source_commit"][:8] + ".lnk")
    if destination.resolve() != destination or destination.exists() or shortcut.exists():
        raise ValueError("E_DELIVERY_INSTALL_EXISTS")
    verify_credential_programs(record, Path(WINDOWS_RUNTIME))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    subprocess.run(  # noqa: S603 -- owned shortcut and verified script.
        [
            r"C:\Windows\System32\cscript.exe",
            "//nologo",
            str(destination / "create-shortcut.vbs"),
            str(shortcut),
            sys.executable,
            str(destination / "launch_part_b.py"),
            str(destination),
        ],
        check=True,
        timeout=15,
    )  # noqa: S603 -- owned shortcut, fixed Windows tool and verified script.
    print("Đã tạo shortcut: " + str(shortcut))
    print(
        "Chrome Windows → profile Betting-Helper → chrome://extensions "
        "→ Developer mode → Load unpacked:"
    )
    print(str(destination / "extension"))
    print("Gói candidate vẫn cần review và các xác nhận riêng trước khi chạy live.")
    return 0


def wsl_menu() -> int:
    from moj_discovery.live_config import load_live_config

    settings = ROOT / ".local/part-b/launcher-settings.json"
    path = ROOT / "config/live-batched.example.json"
    if settings.is_file():
        if settings.resolve() != settings or settings.stat().st_size > 4096:
            raise ValueError("E_LAUNCHER_SETTINGS")
        path = local_config_path(json.loads(settings.read_text())["config"])
    while True:
        print("Cấu hình đang chọn: " + str(path))
        choice = public_input(
            "\n1. Chọn 1 trận mới để probe\n2. Kiểm tra các điều kiện còn thiếu\n"
            "3. Probe provider (xác nhận riêng, tối đa 20 lần / 5 phút)\n"
            "4. Lấy mẫu trang (cần review công cụ, tối đa 10 phút)\n"
            "5. Chạy live chỉ đọc (cần đầy đủ gate, tối đa 120 phút)\n"
            "6. Replay phiên đã đóng\n7. Chọn cấu hình đã được review\n0. Về menu Windows"
        )
        if choice == "0":
            return 0
        try:
            if choice == "1":
                league = int(public_input("League ID của API-Football (Champions League = 2):"))
                season = int(public_input("Season của API-Football (ví dụ 2026):"))
                fixture = int(public_input("Fixture ID chính xác của API-Football:"))
                value = fixture_config(load_live_config(path).public, league, season, fixture)
                value["credentials"] = key_metadata()
                path = (
                    ROOT
                    / ".local/part-b/configs"
                    / ("fixture-" + str(fixture) + "-" + str(uuid4()) + ".json")
                )
                save_json(path, value)
                load_live_config(path)
                save_json(settings, {"config": str(path.relative_to(ROOT))}, replace=True)
                print("Đã lưu cấu hình probe. Live vẫn tắt.")
            elif choice == "2":
                readiness(path)
            elif choice in {"3", "5"}:
                run_action(path, "probe" if choice == "3" else "live-readonly")
            elif choice == "4":
                from tools.prepare_part_b_intent import execute_discovery
                from tools.prepare_part_b_intent import main as prepare

                url = public_input(
                    "URL chính xác của tab Mise-o-jeu đã chọn trong profile Betting-Helper:"
                )
                review = local_config_path(
                    public_input("Đường dẫn .local/part-b/...json của review công cụ từ host:")
                )
                intent = ".local/part-b/intents/observation-" + str(uuid4()) + ".json"
                if (
                    prepare(
                        [
                            "--stage",
                            "operator-discovery",
                            "--config",
                            str(path),
                            "--output",
                            intent,
                            "--operator-url",
                            url,
                        ]
                    )
                    == 0
                ):
                    execute_discovery(
                        [
                            "--config",
                            str(path),
                            "--intent",
                            intent,
                            "--selected-region",
                            "--review",
                            str(review),
                            "--profile-name",
                            "Betting-Helper",
                        ]
                    )
            elif choice == "6":
                from moj_discovery.live_config import private_path
                from tools.qualify_live_readonly import main as replay

                directory = private_path(
                    public_input("Thư mục phiên đã đóng .local/part-b/...:"), root=ROOT
                )
                replay(["--run-dir", str(directory)])
            elif choice == "7":
                selected = local_config_path(
                    public_input("Đường dẫn cấu hình .local/part-b/...json đã review:")
                )
                load_live_config(selected)
                path = selected
                save_json(settings, {"config": str(path.relative_to(ROOT))}, replace=True)
        except (Exception, KeyboardInterrupt):
            print(
                "Chưa thực hiện được: kiểm tra cấu hình, bằng chứng, kho key và terminal. "
                "Không có quyền live tự động."
            )


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if sys.platform == "win32" and sys.argv[1:] == []:
            return windows_menu()
        if sys.platform == "win32" and sys.argv[1:] == ["--install"]:
            return install_windows()
        if sys.platform != "win32" and len(sys.argv) == 4 and sys.argv[1] == "--wsl":
            from moj_discovery.live_intent import source_tree_hash
            from tools.run_command_registry import _git_source_identity

            if (
                _git_source_identity(ROOT)["head"] != sys.argv[2]
                or source_tree_hash(ROOT) != sys.argv[3]
            ):
                raise ValueError("E_DELIVERY_BACKEND_CHANGED")
            return wsl_menu()
    except (Exception, KeyboardInterrupt):
        print("WAITING_PLATFORM: mở shortcut trong terminal Windows của bạn.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
