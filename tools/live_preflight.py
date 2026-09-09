"""Network-free live preflight; only the offline gate may open its owned test browser."""

# ruff: noqa: E402
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.canonical import parse_strict_json
from moj_discovery.input_journal import _read
from moj_discovery.live_preflight import check_live_readiness
from tools.verify_offline_slice import verify_offline_slice


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--offline-result", type=Path)
    args = parser.parse_args()
    try:
        config = cast(dict[str, Any], parse_strict_json(_read(args.config, 262144)))
        result = check_live_readiness(config, {}, {})
        paths = {
            "capture_profile": config["operator"]["capture_profile_path"],
            "platform_qualification": config["runtime"]["platform_qualification_path"],
            **{
                name: config["gates"][name + "_path"]
                for name in ["security_review", "provider_feasibility", "live_run_authorization"]
            },
        }
        # Lane A never opens live profiles, credentials, or purported live approvals.
        evidence = {
            name: {"path_supplied": True} for name, path in paths.items() if path is not None
        }
        name = config["provider"]["api_key_env"]
        result = check_live_readiness(config, evidence, {name: name in os.environ})
        offline_value = args.offline_result or config["gates"]["offline_result_path"]
        offline = Path(offline_value) if offline_value else None
        if offline is not None and not offline.is_absolute():
            offline = ROOT / offline
        rejected = False
        if offline is not None and offline.exists():
            try:
                actual = verify_offline_slice(offline)
                if actual["OFFLINE_SLICE_PASS"] == "YES":  # noqa: S105 -- qualification status, not a secret
                    result["checks"]["offline_gate"] = "PASS"
                else:
                    result["checks"]["offline_gate"] = "SCOPED_RESULT_NOT_ACCEPTANCE"
            except Exception:
                result["checks"]["offline_gate"] = "OFFLINE_EVIDENCE_REJECTED"
                rejected = True
        result["missing_inputs"] = [
            name for name, value in result["checks"].items() if value != "PASS"
        ]
    except Exception:
        print("E_LIVE_PREFLIGHT_CONFIG_REJECTED", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 1 if rejected else 2


if __name__ == "__main__":
    raise SystemExit(main())
