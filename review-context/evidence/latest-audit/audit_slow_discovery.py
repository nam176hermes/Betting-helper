"""Reproduce expired consent preview after slow verification; all inputs synthetic."""

import contextlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from moj_discovery import live_intent, live_preflight_batched, secrets_local
from tests.live.test_run_intents import make_discovery_intent
from tools import prepare_part_b_intent


def main():
    output = Path(__file__).resolve().parent
    root = output / ("slow-verification-synthetic-" + str(uuid4()))
    root.mkdir(mode=0o700)
    calls = []
    now = datetime.now(UTC)

    class Clock(datetime):
        current = datetime.now(UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz else cls.current.replace(tzinfo=None)

    def slow_review(*args):
        calls.append("SYNTHETIC_REVIEW_DELAY_901_SECONDS")
        Clock.current += timedelta(seconds=901)
        return object()

    def forbidden(*args, **kwargs):
        raise AssertionError("No real source or key access permitted")

    with pytest.MonkeyPatch.context() as patch:
        make_discovery_intent(root, patch)
        Clock.current = datetime.now(UTC)
        patch.setattr(prepare_part_b_intent, "ROOT", root)
        patch.setattr(live_intent, "datetime", Clock)
        patch.setattr(live_preflight_batched, "verify_external_review", slow_review)
        patch.setattr(secrets_local, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO("ALLOW OPERATOR OBSERVATION\n")))
        patch.setattr(live_intent, "serve_operator_discovery", forbidden)
        patch.setattr(secrets_local, "obtain_api_football_key", forbidden)
        review = root / ".local/part-b/synthetic-review.json"
        review.write_text(json.dumps({"scope": {"expires_at": (now + timedelta(hours=8)).isoformat()}}))
        transcript = io.StringIO()
        with contextlib.redirect_stdout(transcript):
            code = prepare_part_b_intent.execute_discovery([
                "--config", str(root / "config.json"),
                "--intent", str(root / ".local/part-b/intents/probe.json"),
                "--selected-region", "--review", str(review), "--profile-name", "TEST_ONLY_PROFILE",
            ])
        assert calls == ["SYNTHETIC_REVIEW_DELAY_901_SECONDS"]
        assert code == 2 and "Type ALLOW OPERATOR OBSERVATION" in transcript.getvalue()
        assert "DISCOVERY_NOT_STARTED_OR_REJECTED" in transcript.getvalue()
        assert not (root / ".local/part-b/intent-consumptions.sqlite3").exists()
    (output / "slow-discovery.json").write_text(json.dumps({
        "status": "REPRODUCED", "synthetic_verifier_elapsed_seconds": 901,
        "intent_max_lifetime_seconds": 900, "confirmation_prompt_was_shown_after_expiry": True,
        "launcher_exit": code, "real_provider_attempts": 0, "operator_observations": 0,
        "key_reads": 0, "limitation": "Verifier latency is injected; no real signed live receipt was verified."
    }, indent=2) + "\n")
    print("REPRODUCED: slow verification expires intent, still prompts, then rejects; no real source access")


if __name__ == "__main__":
    main()
