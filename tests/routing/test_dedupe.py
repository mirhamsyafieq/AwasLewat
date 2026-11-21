"""Test penggabungan itinerary identik."""

from backend.routing.dedupe import itinerary_key, merge_duplicates
from backend.routing.models import WALK, Itinerary, Leg


def _leg(route_id: str | None, from_stop: str, to_stop: str) -> Leg:
    mode = WALK if route_id is None else "krl"
    return Leg(mode, route_id, from_stop, to_stop, 1.0, 0.0, 5.0)


def _itinerary(legs: list[Leg], badge: str) -> Itinerary:
    return Itinerary(
        legs=legs, total_min=10.0, total_fare_idr=3_000, transfers=0, badges=[badge]
    )


def test_key_ignores_walk_legs() -> None:
    with_walk = _itinerary([_leg(None, "O", "A"), _leg("R1", "A", "B")], "fastest")
    without_walk = _itinerary([_leg("R1", "A", "B")], "cheapest")
    assert (
        itinerary_key(with_walk) == itinerary_key(without_walk) == (("R1", "A", "B"),)
    )


def test_identical_routes_merged_with_sorted_badges() -> None:
    legs = [_leg("R1", "A", "B")]
    merged = merge_duplicates(
        [_itinerary(legs, "cheapest"), _itinerary(legs, "fastest")]
    )

    assert len(merged) == 1
    assert merged[0].badges == ["fastest", "cheapest"]


def test_different_routes_kept_apart() -> None:
    first = _itinerary([_leg("R1", "A", "B")], "fastest")
    second = _itinerary([_leg("R2", "A", "B")], "cheapest")
    merged = merge_duplicates([first, second])

    assert [itinerary.badges for itinerary in merged] == [["fastest"], ["cheapest"]]


def test_same_route_different_alighting_stop_kept_apart() -> None:
    first = _itinerary([_leg("R1", "A", "B")], "fastest")
    second = _itinerary([_leg("R1", "A", "C")], "cheapest")
    assert len(merge_duplicates([first, second])) == 2


def test_input_not_modified() -> None:
    legs = [_leg("R1", "A", "B")]
    first = _itinerary(legs, "fastest")
    merge_duplicates([first, _itinerary(legs, "cheapest")])
    assert first.badges == ["fastest"]
