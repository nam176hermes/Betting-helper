"""Deterministic generation replacement and bounded spool-capacity decisions."""


class GenerationController:
    def replace_after_gap(self, generations: dict[str, str], current: int) -> dict[str, str]:
        key, successor = str(current), str(current + 1)
        if generations.get(key) != "ACTIVE" or successor in generations:
            raise ValueError("E_GENERATION_SUCCESSOR_BINDING")
        return {**generations, key: "CLOSED", successor: "ACTIVE"}

    def capacity_decision(
        self, *, used: int, incoming: int, normal_limit: int, terminal_reserve: int
    ) -> dict[str, object]:
        if min(used, incoming, normal_limit, terminal_reserve) < 0:
            raise ValueError("E_CAPACITY_INTEGER")
        if used + incoming > normal_limit:
            return {"accepted": False, "status": "SAFETY_STOP", "evicted": 0}
        return {"accepted": True, "status": "NORMAL", "evicted": 0}
