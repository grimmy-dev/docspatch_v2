"""Key validation cache: TTL + hash-mismatch invalidation."""

from docspatch.utils.key_cache import CACHE_TTL_SECONDS, is_validated, mark_validated


def test_mark_then_read_returns_validated(tmp_path):
    p = tmp_path / "cache.json"
    mark_validated("anthropic", "sk-key", path=p)
    assert is_validated("anthropic", "sk-key", path=p)


def test_missing_provider_returns_false(tmp_path):
    p = tmp_path / "cache.json"
    assert is_validated("anthropic", "sk-key", path=p) is False


def test_hash_mismatch_invalidates(tmp_path):
    p = tmp_path / "cache.json"
    mark_validated("anthropic", "sk-old", path=p)
    assert is_validated("anthropic", "sk-new", path=p) is False


def test_expires_after_ttl(tmp_path):
    p = tmp_path / "cache.json"
    mark_validated("anthropic", "sk-key", path=p, now=0.0)
    assert is_validated("anthropic", "sk-key", path=p, now=float(CACHE_TTL_SECONDS - 1))
    assert is_validated("anthropic", "sk-key", path=p, now=float(CACHE_TTL_SECONDS + 1)) is False


def test_only_targeted_provider_is_invalidated_on_key_change(tmp_path):
    p = tmp_path / "cache.json"
    mark_validated("anthropic", "sk-a", path=p)
    mark_validated("openai", "sk-o", path=p)
    # Anthropic key rotated: only its entry should fail; openai still valid.
    assert is_validated("anthropic", "sk-a-new", path=p) is False
    assert is_validated("openai", "sk-o", path=p)
