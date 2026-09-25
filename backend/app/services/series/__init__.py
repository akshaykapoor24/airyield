"""Series / SIT / MICE / Group contracts — inventory, money and deadlines.

Four files, split by what they are allowed to touch:

  * `bases.py`      — what a percentage is a percentage OF. Pure.
  * `rollups.py`    — materialization, margin, and the statuses this stack refuses to
                      store because it has no scheduler to maintain them. Pure.
  * `deadlines.py`  — resolving deadline rules to dates, and keeping the airline's own
                      arithmetic visible when it disagrees with ours. Pure.
  * `matching.py`   — the only one with a session: matches tickets to bookings and
                      cascades the rollups back up the contract.

Three of the four are pure on purpose. This repo's tests run without a database, so
anything that needs proving — the 80% floor counting a child but not a lap infant, a
deposit that is 5% of the net fare rather than of the total, a D-30 name list landing on
27 November — has to be reachable without one.
"""
from app.services.series.matching import SeriesMatchingService, norm_pnr

__all__ = ["SeriesMatchingService", "norm_pnr"]
