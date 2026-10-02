"""Select deterministic P10/P50/P90 representative migration events."""

from __future__ import annotations

PERCENTILES = (10, 50, 90)


def linear_quantile(values: list[float], percentile: int) -> float:
    if not values or not 0 <= percentile <= 100:
        raise ValueError("values must be non-empty and percentile must be in [0,100]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = position - lo
    return ordered[lo] * (1 - fraction) + ordered[hi] * fraction


def select_percentile_events(events: list[dict]) -> list[dict]:
    """Pick distinct actual events nearest linear P10/P50/P90 orbital margins.

    Percentiles are computed over trigger-qualified events, never over 1-second
    samples. A global assignment minimizes total distance to the three target
    quantiles, with event IDs as the deterministic tie breaker.
    """
    if len(events) < len(PERCENTILES):
        raise ValueError("at least three trigger-qualified events are needed")
    ids = [event.get("event_id") for event in events]
    if any(value in (None, "") for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("event_id values must be present and unique")
    margins = [event.get("orbital_margin_s") for event in events]
    if any(not isinstance(value, (int, float)) for value in margins):
        raise ValueError("each event needs a numeric orbital_margin_s")
    targets = [linear_quantile(margins, p) for p in PERCENTILES]
    ordered = sorted(events, key=lambda event: (event["orbital_margin_s"], str(event["event_id"])))
    # The Type-7 targets are ordered. Absolute-distance assignment on a line
    # has an optimum with events in the same order, so prefix DP finds the
    # minimum-cost distinct triple in O(3N).
    previous = [(abs(event["orbital_margin_s"] - targets[0]), (event,)) for event in ordered]
    for target in targets[1:]:
        current = []
        best_prefix = None
        for index, event in enumerate(ordered):
            if index > 0 and previous[index - 1] is not None:
                prior = previous[index - 1]
                prior_key = tuple(str(x["event_id"]) for x in prior[1])
                best_key = (float("inf"), ()) if best_prefix is None else (
                    best_prefix[0], tuple(str(x["event_id"]) for x in best_prefix[1])
                )
                if (prior[0], prior_key) < best_key:
                    best_prefix = prior
            if best_prefix is None:
                current.append(None)
            else:
                current.append((best_prefix[0] + abs(event["orbital_margin_s"] - target),
                                best_prefix[1] + (event,)))
        previous = current
    solutions = [value for value in previous if value is not None]
    _, chosen = min(solutions, key=lambda item: (item[0], tuple(str(x["event_id"]) for x in item[1])))
    result = []
    for percentile, target, event in zip(PERCENTILES, targets, chosen):
        result.append({**event, "percentile_case": f"P{percentile}",
                       "percentile_target_margin_s": target,
                       "distance_to_percentile_target_s": abs(event["orbital_margin_s"] - target)})
    return result
