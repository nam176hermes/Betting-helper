from moj_discovery.diagnostic import render_diagnostic


def test_diagnostic_escapes_text_and_preserves_absent_values() -> None:
    observed = {
        "verified": True,
        "source_kind": "SYNTHETIC_TEST",
        "production_authority": "NONE",
        "MONEY_READY": "NO",
        "OFFLINE_SLICE_PASS": "NO",
        "cases": [{"case_id": "OFF-20", "reason": "<script>alert(1)</script>"}],
    }
    html = render_diagnostic(observed)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "UNKNOWN" in html and "SYNTHETIC ONLY" in html


def test_unverified_upstream_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="E_OFFLINE_UNVERIFIED_DIAGNOSTIC"):
        render_diagnostic({"verified": False})
