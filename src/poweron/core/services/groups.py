from datetime import datetime

from poweron.core.ports import CatalogSource, Repository


class GroupResolver:
    """Daily re-check that a building is still in the same subqueues.

    Payload of `subqueues_changed`: {"subscription_id": int, "label": str,
    "previous": [str], "current": [str], "tracked": [str]}.
    """

    def __init__(self, repository: Repository, source: CatalogSource) -> None:
        self._repository = repository
        self._source = source

    async def resolve(self, now: datetime) -> None:
        raise NotImplementedError
