from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class IndexEntry:
    entity: str
    cis_folder: str
    account_subfolder: str

@dataclass(frozen=True)
class StatementInfo:
    provider: str
    account_number: str
    statement_date: str
    trust_name: str | None = None

    @property
    def year(self) -> str:
        parts = self.statement_date.split("-")
        if len(parts) == 3 and len(parts[2]) == 4:
            return parts[2]
        return str(datetime.now().year)
