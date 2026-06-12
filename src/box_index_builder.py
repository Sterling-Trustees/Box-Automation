import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from boxsdk import Client
from boxsdk.exception import BoxAPIException
from src.models import IndexEntry
from src.exceptions import BoxNavigationError

logger = logging.getLogger(__name__)

_CIS_VARIANTS = {
    "custodial investment statements",
    "custodial investments statements",
    "custodial investment statement",
    "custodial statements",
    "custodian statements",
    "custodial account statements",
    "custodial financial statements",
}

class BoxIndexBuilder:
    _MAX_WORKERS = 3
    _MAX_RETRIES = 5
    _RETRY_BASE_DELAY = 2

    def __init__(self, client: Client) -> None:
        self._client = client

    def build(self) -> dict[str, IndexEntry]:
        le_id = self._find_legal_entities()
        entities = [
            item
            for item in self._client.folder(le_id).get_items(limit=1000)
            if item.type == "folder"
        ]
        logger.info("Scanning %d entities from Box (this takes a few minutes)...", len(entities))

        index: dict[str, IndexEntry] = {}
        lock = Lock()

        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
            futures = {pool.submit(self._scan_entity, e): e for e in entities}
            done = 0
            for future in as_completed(futures):
                result = future.result()
                if result:
                    with lock:
                        index.update(result)
                done += 1
                if done % 100 == 0:
                    logger.info("Progress: %d / %d entities scanned", done, len(entities))

        logger.info("Index built: %d accounts", len(index))
        return index

    _YEAR_NAME_RX = re.compile(r"^(19|20)\d{2}([- ].*)?$")
    _AUX_MARKERS = (
        "account opening", "account documents", "historical statement",
        "household statement", "dividend report", "prior trustee",
        "paperwork", "authorization", "archive", "correspondence",
    )

    def _scan_entity(self, entity) -> dict[str, IndexEntry]:
        entries: dict[str, IndexEntry] = {}
        try:
            for item in self._get_items_with_retry(entity.id, limit=200):
                if item.type == "folder" and item.name.lower() in _CIS_VARIANTS:
                    for acct in self._get_items_with_retry(item.id, limit=500):
                        if acct.type != "folder":
                            continue
                        if acct.name.strip().lower().startswith("closed"):
                            continue
                        self._add_entry(entries, entity.name, item.name, acct.name)
                        if self._should_descend(acct.name):
                            for child in self._get_items_with_retry(acct.id, limit=500):
                                if child.type != "folder":
                                    continue
                                child_name = child.name.strip()
                                if child_name.lower().startswith("closed"):
                                    continue
                                if self._YEAR_NAME_RX.match(child_name):
                                    continue
                                self._add_entry(
                                    entries, entity.name, item.name,
                                    f"{acct.name}/{child.name}",
                                )
                    break
        except Exception as exc:
            logger.debug("Skipped entity '%s': %s", entity.name, exc)
        return entries

    def _add_entry(self, entries: dict, entity_name: str, cis_name: str, subfolder_path: str) -> None:
        leaf = subfolder_path.rsplit("/", 1)[-1]
        leaf_lower = leaf.strip().lower()
        if any(marker in leaf_lower for marker in self._AUX_MARKERS):
            return
        key = self._extract_key(leaf)
        if not key:
            text_key = re.sub(r"[^a-z0-9]", "", subfolder_path.lower())
            if len(text_key) >= 4:
                key = text_key
        if key:
            entries[key] = IndexEntry(
                entity=entity_name,
                cis_folder=cis_name,
                account_subfolder=subfolder_path,
            )

    @classmethod
    def _should_descend(cls, name: str) -> bool:
        for run in re.findall(r"\d{4,}", name):
            if not (1990 <= int(run[:4]) <= 2035 and len(run) == 4):
                return False
        return True

    def _get_items_with_retry(self, folder_id: str, limit: int):
        for attempt in range(self._MAX_RETRIES):
            try:
                return list(self._client.folder(folder_id).get_items(limit=limit))
            except BoxAPIException as exc:
                if exc.status == 429:
                    wait = self._RETRY_BASE_DELAY ** attempt
                    logger.debug("Rate limited — retrying in %ds (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                else:
                    raise
        return []

    def download_all_excels(self) -> list[tuple[str, bytes]]:
        shared_id = self._find_exact("0", "Shared Data")
        if not shared_id:
            raise BoxNavigationError("'Shared Data' not found in Box root")
        checklists_id = self._find_exact(shared_id, "Statement Checklists")
        if not checklists_id:
            raise BoxNavigationError("'Statement Checklists' folder not found in Shared Data")
        items = self._get_items_with_retry(checklists_id, limit=200)
        xlsx_files = [i for i in items if i.type == "file" and i.name.lower().endswith(".xlsx")]
        if not xlsx_files:
            raise BoxNavigationError("No .xlsx checklists found in Statement Checklists")
        results = []
        for f in xlsx_files:
            logger.info("Downloading checklist: %s", f.name)
            results.append((f.name, self._client.file(f.id).content()))
        return results

    def scan_one_entity(self, entity_name: str) -> dict[str, IndexEntry]:
        le_id = self._find_legal_entities()
        entity = self._find_fuzzy(le_id, entity_name)
        if not entity:
            return {}
        return self._scan_entity(entity)

    def _find_fuzzy(self, parent_id: str, target: str):
        import difflib
        items = [i for i in self._get_items_with_retry(parent_id, limit=1000) if i.type == "folder"]
        names = [i.name for i in items]
        target_lower = target.lower()
        for item in items:
            if item.name.lower() in target_lower or target_lower in item.name.lower():
                return item
        matches = difflib.get_close_matches(target, names, n=1, cutoff=0.5)
        if matches:
            return next(i for i in items if i.name == matches[0])
        return None

    def _find_legal_entities(self) -> str:
        shared_id = self._find_exact("0", "Shared Data")
        if not shared_id:
            raise BoxNavigationError("'Shared Data' not found in Box root")
        le_id = self._find_exact(shared_id, "Legal Entities")
        if not le_id:
            raise BoxNavigationError("'Legal Entities' not found in 'Shared Data'")
        return le_id

    def _find_exact(self, parent_id: str, name: str) -> str | None:
        for item in self._get_items_with_retry(parent_id, limit=1000):
            if item.type == "folder" and item.name.lower() == name.lower():
                return item.id
        return None

    @staticmethod
    def _extract_key(folder_name: str) -> str | None:
        candidates: list[str] = []

        for m in re.finditer(r"#([\d\-]+)", folder_name):
            candidates.append(re.sub(r"\D", "", m.group(1)))

        for m in re.finditer(r"\(([\d\-]+)\)", folder_name):
            candidates.append(re.sub(r"\D", "", m.group(1)))

        for m in re.finditer(r"\d{3,}-\d{3,}", folder_name):
            candidates.append(re.sub(r"\D", "", m.group(0)))

        for m in re.finditer(r"\d{5,}", folder_name):
            candidates.append(m.group(0))

        m = re.search(r"([A-Z0-9]*\d[A-Z0-9]*)\s*$", folder_name, re.IGNORECASE)
        if m:
            candidates.append(re.sub(r"\D", "", m.group(1)))

        def _is_year(s: str) -> bool:
            return len(s) == 4 and s.isdigit() and 2000 <= int(s) <= 2030

        valid = [c for c in candidates if c and len(c) >= 5 and not _is_year(c)]
        return max(valid, key=len) if valid else None