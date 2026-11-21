"""Test cache TTL dengan jam palsu (tanpa menunggu sungguhan)."""

from backend.routing.cache import TtlCache, round_point


class FakeClock:
    """Jam yang hanya maju bila disuruh."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_get_returns_value_before_expiry() -> None:
    clock = FakeClock()
    cache: TtlCache[str] = TtlCache(60, clock)
    cache.set("a", "nilai")
    clock.now += 59
    assert cache.get("a") == "nilai"


def test_value_expires_after_ttl() -> None:
    clock = FakeClock()
    cache: TtlCache[str] = TtlCache(60, clock)
    cache.set("a", "nilai")
    clock.now += 60
    assert cache.get("a") is None


def test_missing_key_returns_none() -> None:
    assert TtlCache(60).get("tidak-ada") is None


def test_round_point_merges_nearby_points() -> None:
    # Selisih 0,00001° (~1 m) dianggap titik yang sama.
    assert round_point(-6.200001, 106.800004) == round_point(-6.200004, 106.800001)
    assert round_point(-6.2001, 106.8) != round_point(-6.2002, 106.8)
