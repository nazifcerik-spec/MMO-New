"""Deterministic, platform-independent PRNG (SplitMix64 seeding + xoshiro256**).

Never use Python's global `random` in game logic: its algorithm/seeding may change across versions."""

MASK64 = (1 << 64) - 1


def _rotl(x: int, k: int) -> int:
    return ((x << k) | (x >> (64 - k))) & MASK64


def splitmix64(state: int) -> tuple[int, int]:
    state = (state + 0x9E3779B97F4A7C15) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return state, z ^ (z >> 31)


def derive_seed(seed: int, *labels: str | int) -> int:
    """Stable sub-seed for independent streams (e.g. per encounter)."""
    state = seed & MASK64
    for label in labels:
        for ch in str(label).encode():
            state, value = splitmix64(state ^ ch)
            state = value
    return state


class Rng:
    __slots__ = ("_s", "draws")

    def __init__(self, seed: int) -> None:
        state = seed & MASK64
        s = []
        for _ in range(4):
            state, value = splitmix64(state)
            s.append(value)
        if not any(s):
            s[0] = 1
        self._s = s
        self.draws = 0

    def next_u64(self) -> int:
        s = self._s
        result = (_rotl((s[1] * 5) & MASK64, 7) * 9) & MASK64
        t = (s[1] << 17) & MASK64
        s[2] ^= s[0]
        s[3] ^= s[1]
        s[1] ^= s[2]
        s[0] ^= s[3]
        s[2] ^= t
        s[3] = _rotl(s[3], 45)
        self.draws += 1
        return result

    def random(self) -> float:
        """Uniform float in [0, 1) with 53-bit precision."""
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))

    def chance(self, percent: float) -> bool:
        if percent <= 0:
            return False
        if percent >= 100:
            return True
        return self.random() * 100.0 < percent

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.random()

    def randint(self, lo: int, hi: int) -> int:
        """Inclusive range, unbiased via rejection sampling."""
        if hi < lo:
            raise ValueError("empty range")
        span = hi - lo + 1
        limit = (1 << 64) - ((1 << 64) % span)
        while True:
            v = self.next_u64()
            if v < limit:
                return lo + v % span

    def weighted_index(self, weights: list[float]) -> int:
        total = sum(weights)
        if total <= 0:
            raise ValueError("weights must be positive")
        r = self.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if r < acc:
                return i
        return len(weights) - 1
