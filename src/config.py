import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from src.exceptions import ConfigurationError


@dataclass(frozen=True)
class StatementConfig:
    downloads_folder: Path
    anthropic_api_key: str
    box_client_id: str
    box_client_secret: str
    token_file: Path
    index_cache_path: Path
    excel_path: Path

    @classmethod
    def from_env(cls) -> "StatementConfig":
        load_dotenv()
        base = Path(__file__).parent.parent
        return cls(
            downloads_folder=Path(os.getenv("DOWNLOADS_FOLDER") or Path.home() / "Downloads"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            box_client_id=os.getenv("BOX_CLIENT_ID", ""),
            box_client_secret=os.getenv("BOX_CLIENT_SECRET", ""),
            token_file=base / "token_storage.json",
            index_cache_path=base / "index_cache.json",
            excel_path=base / "checklist_cache.xlsx",
        )

    def validate(self) -> None:
        missing = [
            name for name, val in [
                ("ANTHROPIC_API_KEY", self.anthropic_api_key),
                ("BOX_CLIENT_ID", self.box_client_id),
                ("BOX_CLIENT_SECRET", self.box_client_secret),
            ]
            if not val
        ]
        if missing:
            raise ConfigurationError(f"Missing in .env: {', '.join(missing)}")
        if not self.downloads_folder.exists():
            raise ConfigurationError(f"Downloads folder not found: {self.downloads_folder}")
        if not self.token_file.exists():
            raise ConfigurationError("Box not authenticated. Run: python setup_box_auth.py")
