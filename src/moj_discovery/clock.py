from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

_CLOSURE_REASONS = frozenset(
    {
        "DOMAIN_BOOT_CHANGED",
        "MONOTONIC_REGRESSION",
        "WALL_CLOCK_STEP",
        "SLEEP_RESUME",
        "MAX_DURATION",
        "RTT_EXCEEDED",
        "UNCERTAINTY_EXCEEDED",
        "INCONSISTENT_MAPPING",
        "LIFECYCLE_INVALIDATED",
        "RUN_CLOSED",
    }
)


@dataclass(frozen=True)
class MappingClosure:
    mapping_id: str
    reason: str
    permanent: bool = True
    reopen_permitted: bool = False


class ClockMapper:
    def select(
        self,
        candidates: Iterable[Mapping[str, object]],
        history: Sequence[MappingClosure] = (),
    ) -> Mapping[str, object]:
        closed = {closure.mapping_id for closure in history}
        eligible = [
            candidate for candidate in candidates if candidate.get("mapping_id") not in closed
        ]
        for candidate in eligible:
            mapping_id = candidate.get("mapping_id")
            width = candidate.get("width_us")
            valid_from = candidate.get("valid_from_us")
            if (
                not isinstance(mapping_id, str)
                or not mapping_id
                or type(width) is not int
                or width < 0
                or type(valid_from) is not int
                or valid_from < 0
            ):
                raise ValueError("E_INVALID_MAPPING_CANDIDATE")
        if not eligible:
            raise ValueError("E_NO_VALID_MAPPING")
        return min(
            eligible,
            key=lambda candidate: (
                candidate["width_us"],
                -candidate["valid_from_us"],  # type: ignore[operator]
                candidate["mapping_id"],
            ),
        )

    def close(
        self,
        mapping_id: str,
        reason: str,
        history: Sequence[MappingClosure] = (),
    ) -> tuple[MappingClosure, ...]:
        if not mapping_id or reason not in _CLOSURE_REASONS:
            raise ValueError("E_INVALID_MAPPING_CLOSURE")
        if any(closure.mapping_id == mapping_id for closure in history):
            raise ValueError("E_MAPPING_PERMANENTLY_CLOSED")
        return (*history, MappingClosure(mapping_id, reason))

    def reopen(self, mapping_id: str, history: Sequence[MappingClosure]) -> None:
        if any(closure.mapping_id == mapping_id for closure in history):
            raise ValueError("E_MAPPING_PERMANENTLY_CLOSED")
        raise ValueError("E_NO_VALID_MAPPING")
