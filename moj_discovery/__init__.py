"""Source-layout import shim for a non-packaged uv bootstrap project."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "moj_discovery")]
