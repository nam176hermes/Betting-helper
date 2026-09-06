import re
from datetime import datetime
from urllib.parse import urlsplit

from jsonschema import FormatChecker  # type: ignore[import-untyped]

STRICT_FORMAT_CHECKER = FormatChecker()


@STRICT_FORMAT_CHECKER.checks("date-time", raises=ValueError)  # type: ignore[untyped-decorator]
def _is_rfc3339_date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if (
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})",
            value,
        )
        is None
    ):
        return False
    parsed = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


@STRICT_FORMAT_CHECKER.checks("uri", raises=ValueError)  # type: ignore[untyped-decorator]
def _is_uri(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if any(ord(character) <= 0x20 for character in value):
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value) is None:
        return False
    if re.search(r"%(?![0-9A-Fa-f]{2})", value) is not None:
        return False
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and not parsed.hostname:
        return False
    _ = parsed.port
    return True
