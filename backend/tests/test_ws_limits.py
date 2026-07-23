from api.ws.limits import RateLimiter


def test_allows_up_to_max_then_blocks():
    limiter = RateLimiter(max_per_second=2)
    assert limiter.is_limited() is False
    assert limiter.is_limited() is False
    assert limiter.is_limited() is True


def test_window_evicts_old_entries(monkeypatch):
    import api.ws.limits as limits_module

    fake_now = {"t": 100.0}
    monkeypatch.setattr(
        limits_module.time, "monotonic", lambda: fake_now["t"]
    )
    limiter = RateLimiter(max_per_second=1)
    assert limiter.is_limited() is False
    assert limiter.is_limited() is True
    # Advance beyond the 1s window; the old entry is evicted.
    fake_now["t"] = 102.0
    assert limiter.is_limited() is False
