from app.game_engine.rng import Rng, derive_seed


def test_rng_golden_values_are_stable() -> None:
    r = Rng(42)
    assert [r.next_u64() for _ in range(3)] == [1546998764402558742, 6990951692964543102, 12544586762248559009]


def test_rng_reproducible_and_seed_sensitive() -> None:
    a, b, c = Rng(7), Rng(7), Rng(8)
    seq_a = [a.random() for _ in range(100)]
    assert seq_a == [b.random() for _ in range(100)]
    assert seq_a != [c.random() for _ in range(100)]
    assert all(0.0 <= x < 1.0 for x in seq_a)


def test_rng_distribution_sanity() -> None:
    r = Rng(123)
    hits = sum(r.chance(25) for _ in range(20000))
    assert 4600 < hits < 5400
    counts = [0, 0, 0]
    for _ in range(9000):
        counts[r.weighted_index([1, 2, 6])] += 1
    assert counts[0] < counts[1] < counts[2]
    assert all(1 <= r.randint(1, 6) <= 6 for _ in range(1000))


def test_derive_seed_is_stable_and_label_sensitive() -> None:
    assert derive_seed(99, "enc", 1) == derive_seed(99, "enc", 1)
    assert derive_seed(99, "enc", 1) != derive_seed(99, "enc", 2)
