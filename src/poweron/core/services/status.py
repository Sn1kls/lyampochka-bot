from poweron.core.domain.models import StatusReport
from poweron.core.ports import Repository


class Status:
    def __init__(self, repository: Repository, version: str) -> None:
        self._repository = repository
        self._version = version

    async def report(self) -> StatusReport:
        raise NotImplementedError
