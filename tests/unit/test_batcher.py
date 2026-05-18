"""Tests for greedy_batches — atomic items, never split."""

import pytest

from docspatch.utils.batcher import Batch, greedy_batches


def size_int(x: int) -> int:
    return x


def test_empty_input_returns_empty_plan():
    plan = greedy_batches([], size_int, limit=10)
    assert plan.batches == ()
    assert plan.batch_count == 0
    assert plan.item_count == 0


def test_single_item_fits_in_one_batch():
    plan = greedy_batches([4], size_int, limit=10)
    assert plan.batch_count == 1
    assert plan.batches[0].items == (4,)
    assert plan.batches[0].total_size == 4
    assert not plan.batches[0].oversized


def test_greedy_fills_until_next_would_exceed():
    plan = greedy_batches([3, 3, 3, 3], size_int, limit=8)
    # 3+3=6, +3=9 > 8 → flush. Second batch 3+3=6.
    assert plan.batch_count == 2
    assert plan.batches[0].items == (3, 3)
    assert plan.batches[1].items == (3, 3)


def test_oversized_item_isolated_with_flag():
    plan = greedy_batches([2, 50, 2], size_int, limit=10)
    assert plan.batch_count == 3
    assert plan.batches[0].items == (2,)
    assert plan.batches[1].items == (50,)
    assert plan.batches[1].oversized is True
    assert plan.batches[2].items == (2,)


def test_oversized_flushes_pending_batch_first():
    plan = greedy_batches([3, 3, 100, 3], size_int, limit=10)
    assert plan.batches[0].items == (3, 3)
    assert plan.batches[1].items == (100,)
    assert plan.batches[1].oversized is True
    assert plan.batches[2].items == (3,)


def test_order_preserved_across_batches():
    items = list(range(1, 8))
    plan = greedy_batches(items, size_int, limit=10)
    flat = [i for b in plan.batches for i in b.items]
    assert flat == items


def test_every_item_appears_exactly_once():
    items = [4, 4, 4, 4, 4]
    plan = greedy_batches(items, size_int, limit=10)
    flat = [i for b in plan.batches for i in b.items]
    assert sorted(flat) == sorted(items)
    assert plan.item_count == len(items)


def test_invalid_limit_raises():
    with pytest.raises(ValueError):
        greedy_batches([1], size_int, limit=0)
    with pytest.raises(ValueError):
        greedy_batches([1], size_int, limit=-5)


def test_negative_size_raises():
    with pytest.raises(ValueError):
        greedy_batches([1], lambda _x: -1, limit=10)


def test_batch_frozen_and_immutable_items_tuple():
    plan = greedy_batches([1, 2, 3], size_int, limit=10)
    b = plan.batches[0]
    assert isinstance(b.items, tuple)
    with pytest.raises((AttributeError, TypeError)):
        b.items = ()  # type: ignore[misc]


def test_oversized_batch_constructor_rejects_multi_item():
    with pytest.raises(ValueError):
        Batch(items=(1, 2), total_size=2, oversized=True)


def test_plan_total_size_correct():
    plan = greedy_batches([3, 3, 3, 3], size_int, limit=8)
    assert plan.total_size == 12
    assert plan.oversized_count == 0
