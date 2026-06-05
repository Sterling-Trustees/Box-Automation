import json
import logging
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path
from src.models import IndexEntry
from src.box_index_builder import BoxIndexBuilder
from src.excel_index import ExcelIndex

logger = logging.getLogger(__name__)


class LiveIndex:
    _TTL_HOURS = 48

    def __init__(self, builder: BoxIndexBuilder, cache_path: Path) -> None:
        self._builder = builder
        self._cache_path = cache_path
        self._index: dict[str, IndexEntry] = {}
        self._excel: ExcelIndex | None = None
        self._lock = threading.RLock()
        self._rebuild_lock = threading.Lock()
        self._boot()
        self._start_refresh_thread()

    def lookup(self, account_number: str) -> IndexEntry | None:
        pdf_digits = re.sub(r"\D", "", account_number)

        result = self._search(pdf_digits)
        if result is not None:
            return result

        if self._excel:
            result = self._excel_fallback(account_number, pdf_digits)
            if result is not None:
                return result

        logger.info("Not found in Box or Excel — rebuilding both from Box...")
        self._rebuild()

        result = self._search(pdf_digits)
        if result is not None:
            return result

        if self._excel:
            result = self._excel_fallback(account_number, pdf_digits)

        return result

    def __len__(self) -> int:
        with self._lock:
            return len(self._index)

    def excel_len(self) -> int:
        return len(self._excel) if self._excel else 0

    def _search(self, pdf_digits: str) -> IndexEntry | None:
        with self._lock:
            if pdf_digits in self._index:
                return self._index[pdf_digits]
            for key, entry in self._index.items():
                if key and len(key) >= 5 and key in pdf_digits:
                    return entry
            for key, entry in self._index.items():
                if pdf_digits and len(pdf_digits) >= 5 and pdf_digits in key:
                    return entry
        return None

    def _excel_fallback(self, account_number: str, pdf_digits: str) -> IndexEntry | None:
        trust_name = self._excel.lookup_trust(account_number)
        if not trust_name:
            logger.warning("Account '%s' not found in Box index or Excel checklist.", account_number)
            return None

        logger.info("Excel matched account → '%s'. Scanning Box entity...", trust_name)
        entries = self._builder.scan_one_entity(trust_name)
        if not entries:
            logger.warning("No indexed accounts found in Box for '%s'.", trust_name)
            return None

        with self._lock:
            self._index.update(entries)
        self._save_cache(self._index)

        result = self._search(pdf_digits)
        if result:
            return result
        return next(iter(entries.values()))

    def _boot(self) -> None:
        self._refresh_excel()
        cached = self._load_cache()
        if cached is not None and not self._is_stale():
            with self._lock:
                self._index = cached
            logger.info("Index loaded from cache: %d accounts", len(self._index))
        else:
            self._rebuild()

    def _rebuild(self) -> None:
        if not self._rebuild_lock.acquire(blocking=False):
            self._rebuild_lock.acquire()
            self._rebuild_lock.release()
            return
        try:
            logger.info("Rebuilding Box index and refreshing Excel from Box...")
            self._refresh_excel()
            new_index = self._builder.build()
            with self._lock:
                self._index = new_index
            self._save_cache(new_index)
        finally:
            self._rebuild_lock.release()

    def _refresh_excel(self) -> None:
        try:
            files = self._builder.download_all_excels()
            new_excel = ExcelIndex.from_bytes_list(files)
            with self._lock:
                self._excel = new_excel
        except Exception as exc:
            logger.warning("Could not refresh Excel from Box: %s", exc)

    def _load_excel(self) -> ExcelIndex | None:
        return None

    def _start_refresh_thread(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self._TTL_HOURS * 3600)
                logger.info("Scheduled 48h refresh starting...")
                self._rebuild()

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()

    def _load_cache(self) -> dict[str, IndexEntry] | None:
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return {k: IndexEntry(**v) for k, v in data.get("index", {}).items()}
        except Exception:
            return None

    def _save_cache(self, index: dict[str, IndexEntry]) -> None:
        payload = {
            "timestamp": time.time(),
            "index": {k: asdict(v) for k, v in index.items()},
        }
        self._cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _is_stale(self) -> bool:
        if not self._cache_path.exists():
            return True
        try:
            ts = json.loads(self._cache_path.read_text(encoding="utf-8")).get("timestamp", 0)
            return (time.time() - ts) > (self._TTL_HOURS * 3600)
        except Exception:
            return True
