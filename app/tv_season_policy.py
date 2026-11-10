"""Plan TV season staging and restoration from a verified inventory."""
from dataclasses import dataclass

ARCHIVE = 'tv_leaving_soon_seasons'


@dataclass(frozen=True)
class SeasonPlan:
    latest: int | None = None
    stage: tuple[int, ...] = ()
    restore: tuple[int, ...] = ()
    blocked: bool = False


def plan_seasons(*, tags, active, leaving_soon, verified, keep_all_tag='keep-all-seasons'):
    """Use season numbers that have verified episodes in either location.

    The caller must check the show identity, tags, and both folder inventories.
    This only proposes staging or restoration; it never approves deletion.
    """
    if verified is not True or tags is None:
        return SeasonPlan(blocked=True)
    if isinstance(tags, str) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError('Season policy requires verified tag names')
    active, leaving_soon = set(active), set(leaving_soon)
    if any(type(number) is not int or number < 0 for number in active | leaving_soon):
        raise ValueError('Season inventory requires nonnegative season numbers')
    if active & leaving_soon:
        return SeasonPlan(blocked=True)

    normalized = {tag.casefold() for tag in tags}
    regular = (active | leaving_soon) - {0}
    latest = max(regular, default=None)
    if normalized.intersection({'keep-all', 'keep-all-seasons', 'keep-forever', keep_all_tag.casefold()}):
        return SeasonPlan(latest=latest, restore=tuple(sorted(leaving_soon - {0})))
    if 'one-season' not in normalized or latest is None:
        return SeasonPlan(latest=latest)
    return SeasonPlan(latest=latest,
                      stage=tuple(sorted(number for number in active if 0 < number < latest)),
                      restore=(latest,) if latest in leaving_soon else ())
