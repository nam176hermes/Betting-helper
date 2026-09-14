"""Plan arithmetic oracle; no network, keys, databases or repository writes."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from math import ceil

@dataclass(frozen=True)
class Budget:
    periodic: int
    overhead: int
    fallback: int
    calls: int
    with_reserve: int

def estimate(segments: list[tuple[int, int]], *, setup: int = 3,
             confirmations: int = 2, fallback_calls: int = 0,
             reserve: str = '0.20') -> Budget:
    if any(type(x) is not int or x < 0 for x in (setup, confirmations, fallback_calls)):
        raise ValueError('invalid count')
    if any(type(t) is not int or type(d) is not int or t < 0 or d <= 0 for t,d in segments):
        raise ValueError('invalid interval')
    r=Decimal(reserve)
    if not r.is_finite() or not Decimal(0) <= r <= Decimal(1):
        raise ValueError('invalid reserve')
    periodic=sum(ceil(t/d) for t,d in segments)
    calls=periodic+setup+confirmations+fallback_calls
    maximum=int((Decimal(calls)*(Decimal(1)+r)).to_integral_value(rounding=ROUND_CEILING))
    return Budget(periodic,setup+confirmations,fallback_calls,calls,maximum)

def batch_ids(ids: list[int]) -> list[tuple[int,...]]:
    if any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError('invalid fixture id')
    ordered=sorted(set(ids))
    return [tuple(ordered[i:i+20]) for i in range(0,len(ordered),20)]
