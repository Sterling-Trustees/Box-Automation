import json
import os
import re
from pathlib import Path
from boxsdk import OAuth2, Client
from boxsdk.exception import BoxAPIException
from src.exceptions import BoxNavigationError, ConfigurationError

class TokenStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def save(self, access_token: str, refresh_token: str) -> None:
        self._path.write_text(
            json.dumps({"access_token": access_token, "refresh_token": refresh_token})
        )
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def load(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigurationError(
                f"Token file corrupted or unreadable: {self._path}. "
                "Run: python setup_box_auth.py"
            ) from exc

def build_client(client_id: str, client_secret: str, token_store: TokenStore) -> Client:
    tokens = token_store.load()
    oauth = OAuth2(
        client_id=client_id,
        client_secret=client_secret,
        store_tokens=token_store.save,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )
    return Client(oauth)

class BoxUploader:
    _ROOT_ID = "0"

    def __init__(self, client: Client) -> None:
        self._client = client
        self._legal_entities_id: str | None = None

    def find_upload_folder(
        self,
        entity: str,
        cis_folder: str,
        account_subfolder: str,
        year: str,
    ) -> str:
        le_id = self._get_legal_entities_id()
        entity_id = self._find_exact(le_id, entity)
        if not entity_id:
            raise BoxNavigationError(f"Entity folder not found: '{entity}'")
        cis_id = self._find_exact(entity_id, cis_folder)
        if not cis_id:
            raise BoxNavigationError(f"'{cis_folder}' not found inside '{entity}'")

        acct_id = cis_id
        for part in account_subfolder.split("/"):
            next_id = self._find_exact(acct_id, part)
            if not next_id:
                raise BoxNavigationError(f"Account folder not found: '{part}' (path: '{account_subfolder}')")
            acct_id = next_id

        return self._get_or_create(acct_id, year)

    _DATE_RX = re.compile(r"(?<!\d)(\d{1,2})([-._/ ])(\d{1,2})\2(\d{2,4})(?!\d)")
    _MONTH_YEAR_RX = re.compile(r"(?<!\d)(\d{1,2})[-._/ ](\d{4})(?!\d)")
    _YEAR_MONTH_RX = re.compile(r"(?<!\d)(\d{4})[-._/ ](\d{1,2})(?!\d)")

    @staticmethod
    def _normalize(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    @classmethod
    def _date_key(cls, name: str) -> str | None:
        for m in cls._DATE_RX.finditer(name):
            month, day, year = int(m.group(1)), int(m.group(3)), int(m.group(4))
            if year < 100:
                year += 2000
            if 1 <= month <= 12 and 1 <= day <= 31 and 1990 <= year <= 2100:
                return f"{month:02d}-{year}"
        for m in cls._MONTH_YEAR_RX.finditer(name):
            month, year = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12 and 1990 <= year <= 2100:
                return f"{month:02d}-{year}"
        for m in cls._YEAR_MONTH_RX.finditer(name):
            year, month = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12 and 1990 <= year <= 2100:
                return f"{month:02d}-{year}"
        return None

    def _is_duplicate(self, remote_name: str, existing: list[str]) -> bool:
        remote_norm = self._normalize(remote_name)
        if any(self._normalize(n) == remote_norm for n in existing):
            return True
        date_key = self._date_key(remote_name)
        if date_key and any(self._date_key(n) == date_key for n in existing):
            return True
        return False

    def upload(self, folder_id: str, local_path: Path, remote_name: str) -> bool:
        existing = [
            item.name
            for item in self._client.folder(folder_id).get_items(limit=1000)
            if item.type == "file"
        ]
        if self._is_duplicate(remote_name, existing):
            return False
        try:
            with open(local_path, "rb") as f:
                self._client.folder(folder_id).upload_stream(f, remote_name)
            return True
        except BoxAPIException as exc:
            if exc.status == 409:
                return False
            raise

    def _get_legal_entities_id(self) -> str:
        if self._legal_entities_id:
            return self._legal_entities_id
        shared_id = self._find_exact(self._ROOT_ID, "Shared Data")
        if not shared_id:
            raise BoxNavigationError("'Shared Data' not found in Box root")
        le_id = self._find_exact(shared_id, "Legal Entities")
        if not le_id:
            raise BoxNavigationError("'Legal Entities' not found in 'Shared Data'")
        self._legal_entities_id = le_id
        return le_id

    def _find_exact(self, parent_id: str, name: str) -> str | None:
        for folder in self._client.folder(parent_id).get_items(limit=1000):
            if folder.type == "folder" and folder.name.lower() == name.lower():
                return folder.id
        return None

    def _get_or_create(self, parent_id: str, name: str) -> str:
        folder_id = self._find_exact(parent_id, name)
        if folder_id:
            return folder_id
        return self._client.folder(parent_id).create_subfolder(name).id
