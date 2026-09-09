"""Static escaped accounting diagnostics, never observed match data."""

from html import escape
from typing import Any


def render_diagnostic(result: dict[str, Any]) -> str:
    if (
        result.get("verified") is not True
        or result.get("source_kind") != "SYNTHETIC_TEST"
        or result.get("production_authority") != "NONE"
        or result.get("MONEY_READY") != "NO"
        or not isinstance(result.get("cases"), list)
    ):
        raise ValueError("E_OFFLINE_UNVERIFIED_DIAGNOSTIC")

    def text(value: object) -> str:
        return escape("UNKNOWN" if value is None else str(value), quote=True)

    rows = "".join(
        "<tr>"
        + "".join(
            "<td>" + text(case.get(field)) + "</td>"
            for field in (
                "case_id",
                "actual_count",
                "highest_sequence",
                "ack",
                "gap_count",
                "replay",
                "reason",
            )
        )
        + "</tr>"
        for case in result["cases"]
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="'
        "default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>Synthetic offline accounting</title><style>"
        "body{font:16px system-ui;margin:2rem;max-width:80rem}"
        "table{border-collapse:collapse}"
        "th,td{padding:.5rem;border:1px solid #aaa;text-align:left}</style>"
        "<body><h1>SYNTHETIC ONLY</h1><p>No observed match data.</p><p>Offline slice: "
        + text(result.get("OFFLINE_SLICE_PASS"))
        + "</p><p>Run: "
        + text(result.get("run_id"))
        + "</p><p>Source revision: "
        + text(result.get("code_revision"))
        + "</p><p>Source age: UNKNOWN</p><table><thead><tr><th>Case</th><th>Committed rows</th>"
        "<th>Highest sequence</th><th>ACK</th><th>Gaps</th>"
        "<th>Replay</th><th>Reason</th></tr></thead>"
        "<tbody>"
        + rows
        + "</tbody></table><p>Live read-only: PENDING_REAL_INPUTS_AND_LIVE_REVIEW</p>"
        "<p>Money ready: NO · Production authority: NONE</p></body></html>"
    )
