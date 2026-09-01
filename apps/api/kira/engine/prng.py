"""A deterministic integer generator, written here because the engine may not
import ``random``.

xorshift64* over 64-bit integers. Pure integer arithmetic, no float, no clock,
and identical on every Python version — which matters, because a golden file
records what it produced.
"""

from __future__ import annotations

_MASK = (1 << 64) - 1
_MULTIPLIER = 0x2545F4914F6CDD1D
_GOLDEN = 0x9E3779B97F4A7C15


class Prng:
    """Deterministic given its seed. Not cryptographic, and not trying to be."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an int")
        state = seed & _MASK
        # Zero is a fixed point of xorshift, so it is displaced rather than used.
        self._state = state if state else _GOLDEN

    def next_u64(self) -> int:
        x = self._state
        x ^= x >> 12
        x ^= (x << 25) & _MASK
        x ^= x >> 27
        self._state = x
        return (x * _MULTIPLIER) & _MASK

    def below(self, bound: int) -> int:
        """A uniform integer in ``[0, bound)``.

        Rejection sampling rather than a bare modulo: with a bound that does not
        divide 2**64, modulo would quietly favour the low buckets, and a biased
        simulation is worse than a slow one.
        """
        if isinstance(bound, bool) or not isinstance(bound, int):
            raise TypeError("bound must be an int")
        if bound <= 0:
            raise ValueError("bound must be positive")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound
