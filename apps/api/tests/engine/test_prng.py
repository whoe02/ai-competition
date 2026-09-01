"""The simulation's randomness is a fixture, not a surprise."""

import pytest

from kira.engine.prng import Prng


def test_same_seed_gives_the_same_sequence():
    assert [Prng(42).next_u64() for _ in range(5)] == [Prng(42).next_u64() for _ in range(5)]


def test_different_seeds_diverge():
    assert Prng(1).next_u64() != Prng(2).next_u64()


def test_zero_seed_is_not_a_dead_generator():
    stream = Prng(0)
    assert len({stream.next_u64() for _ in range(20)}) == 20


def test_below_stays_in_range():
    stream = Prng(7)
    assert all(0 <= stream.below(13) < 13 for _ in range(500))


def test_below_covers_its_range():
    stream = Prng(7)
    assert {stream.below(5) for _ in range(400)} == {0, 1, 2, 3, 4}


def test_below_is_roughly_uniform():
    """Rejection sampling, not modulo bias: no bucket should run away."""
    stream = Prng(99)
    counts = [0] * 10
    for _ in range(20_000):
        counts[stream.below(10)] += 1
    assert max(counts) - min(counts) < 700


def test_below_rejects_a_non_positive_bound():
    with pytest.raises(ValueError):
        Prng(1).below(0)


def test_seed_must_be_an_int():
    with pytest.raises(TypeError):
        Prng("42")


def test_a_bool_is_not_an_int_here():
    with pytest.raises(TypeError):
        Prng(True)
