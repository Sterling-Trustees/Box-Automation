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

    def lookup(
        self,
        account_number: str,
        provider: str = "",
        trust_name: str = "",
        fund_name: str = "",
    ) -> IndexEntry | None:
        pdf_digits = re.sub(r"\D", "", account_number)

        result = self._search_all(account_number, pdf_digits, provider, trust_name, fund_name)
        if result is not None:
            return result

        if not self._confirm_rebuild():
            logger.info("Rebuild declined — file will be skipped.")
            return None

        logger.info("Rebuilding full Box index...")
        self._rebuild()

        return self._search_all(account_number, pdf_digits, provider, trust_name, fund_name)

    @staticmethod
    def _confirm_rebuild() -> bool:
        try:
            answer = input(
                "\nAccount not found via any lookup layer.\n"
                "Rebuild the full Box index now? This takes a few minutes. [y/n]: "
            )
        except (EOFError, OSError):
            return False
        return answer.strip().lower() in ("y", "yes")

    def _search_all(
        self,
        account_number: str,
        pdf_digits: str,
        provider: str,
        trust_name: str,
        fund_name: str,
    ) -> IndexEntry | None:
        result = self._numeric_search(pdf_digits)
        if result is not None:
            return result

        if self._excel:
            result = self._excel_fallback(account_number, pdf_digits, provider)
            if result is not None:
                return result

        if provider:
            result = self._text_search(provider, trust_name)
            if result is not None:
                return result

        if fund_name:
            result = self._token_search(fund_name, trust_name)
            if result is not None:
                return result

        if trust_name:
            result = self._trust_scoped_account_match(trust_name, pdf_digits)
            if result is not None:
                return result

        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._index)

    def excel_len(self) -> int:
        return len(self._excel) if self._excel else 0

    def _numeric_search(self, pdf_digits: str) -> IndexEntry | None:
        with self._lock:
            if pdf_digits in self._index:
                return self._index[pdf_digits]
            for key, entry in self._index.items():
                if key and len(key) >= 5 and key.isdigit() and key in pdf_digits:
                    return entry
            for key, entry in self._index.items():
                if pdf_digits and len(pdf_digits) >= 5 and key.isdigit() and pdf_digits in key:
                    return entry
        return None

    _STOP_TOKENS = {
        "fund", "funds", "ltd", "lp", "llc", "llp", "inc", "the", "of", "and",
        "class", "series", "units", "trust", "co", "plc",
        "statement", "statements", "stmt", "stmts", "account", "accounts", "acct",
    }

    _TRUST_STOP_TOKENS = {"the", "trust", "tst", "of", "u", "a", "ua", "dtd", "ttee", "ttees", "llc"}

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    @classmethod
    def _trust_matches(cls, trust_name: str, entity: str) -> bool:
        t_norm, e_norm = cls._norm(trust_name), cls._norm(entity)
        if not t_norm or not e_norm:
            return False
        if t_norm in e_norm or e_norm in t_norm:
            return True
        t_tokens = [t for t in re.findall(r"[a-z0-9]+", trust_name.lower()) if t not in cls._TRUST_STOP_TOKENS]
        e_tokens = [t for t in re.findall(r"[a-z0-9]+", entity.lower()) if t not in cls._TRUST_STOP_TOKENS]
        if not t_tokens or not e_tokens:
            return False
        short, long_ = (t_tokens, e_tokens) if len(t_tokens) <= len(e_tokens) else (e_tokens, t_tokens)

        def tok_match(a: str, b: str) -> bool:
            return a == b or (len(a) >= 3 and b.startswith(a)) or (len(b) >= 3 and a.startswith(b))

        matched = sum(1 for s in short if any(tok_match(s, l) for l in long_))
        return matched == len(short) and matched >= 2

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return {
            t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) >= 3 and t not in cls._STOP_TOKENS
        }

    def _token_search(self, fund_name: str, trust_name: str) -> IndexEntry | None:
        if not trust_name:
            return None
        fund_tokens = self._tokens(fund_name)
        if not fund_tokens:
            return None

        with self._lock:
            unique_entries = {
                (e.entity, e.account_subfolder): e for e in self._index.values()
            }.values()
            scored: list[tuple[int, int, IndexEntry]] = []
            for entry in unique_entries:
                if not self._trust_matches(trust_name, entry.entity):
                    continue
                overlap = fund_tokens & self._tokens(entry.account_subfolder)
                if overlap:
                    scored.append((len(overlap), max(len(t) for t in overlap), entry))

        if not scored:
            return None
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        top_count, top_len, top_entry = scored[0]
        if len(scored) > 1 and scored[1][0] == top_count:
            logger.warning(
                "Fund '%s' matches multiple folders equally well in '%s' — skipping to avoid a wrong upload.",
                fund_name, trust_name,
            )
            return None
        if top_count >= 2 or top_len >= 6:
            return top_entry
        return None

    def _provider_matches(self, entry: IndexEntry, provider_norm: str) -> bool:
        subfolder_norm = self._norm(entry.account_subfolder)
        entity_norm = self._norm(entry.entity)
        fund_part = (
            subfolder_norm[len(entity_norm):]
            if subfolder_norm.startswith(entity_norm)
            else subfolder_norm
        )
        return (
            (len(provider_norm) >= 4 and provider_norm in subfolder_norm) or
            (len(fund_part) >= 4 and fund_part in provider_norm)
        )

    def _text_search(self, provider: str, trust_name: str = "") -> IndexEntry | None:
        provider_norm = self._norm(provider)
        trust_norm = self._norm(trust_name) if trust_name else ""

        if len(provider_norm) < 4:
            return None

        matches: list[IndexEntry] = []
        with self._lock:
            for entry in self._index.values():
                if not self._provider_matches(entry, provider_norm):
                    continue
                if trust_norm:
                    if self._trust_matches(trust_name, entry.entity):
                        return entry
                else:
                    matches.append(entry)

        if not trust_norm:
            unique = {(m.entity, m.account_subfolder) for m in matches}
            if len(unique) == 1:
                return matches[0]
            if len(unique) > 1:
                logger.warning(
                    "Provider '%s' matches %d folders across different entities and no trust name "
                    "was extracted to disambiguate — skipping to avoid filing into the wrong trust.",
                    provider, len(unique),
                )
        return None

    @staticmethod
    def _is_year_like(digits: str) -> bool:
        return len(digits) == 4 and 1990 <= int(digits) <= 2035

    @classmethod
    def _account_digits_match(cls, subfolder: str, pdf_digits: str) -> bool:
        if len(pdf_digits) < 4:
            return False
        for run in re.findall(r"\d{4,}", subfolder):
            if cls._is_year_like(run):
                continue
            if run in pdf_digits:
                return True
        return False

    def _local_account_match(self, entries, pdf_digits: str) -> IndexEntry | None:
        unique = {(e.entity, e.account_subfolder): e for e in entries}.values()
        matched = [e for e in unique if self._account_digits_match(e.account_subfolder, pdf_digits)]
        if len(matched) == 1:
            return matched[0]
        return None

    def _trust_scoped_account_match(self, trust_name: str, pdf_digits: str) -> IndexEntry | None:
        if not self._norm(trust_name):
            return None
        with self._lock:
            scoped = [
                e for e in self._index.values()
                if self._trust_matches(trust_name, e.entity)
            ]
        return self._local_account_match(scoped, pdf_digits)

    def _excel_fallback(self, account_number: str, pdf_digits: str, provider: str = "") -> IndexEntry | None:
        excel_trust = self._excel.lookup_trust(account_number)
        if not excel_trust:
            return None

        logger.info("Excel matched account → '%s'. Scanning Box entity...", excel_trust)
        entries = self._builder.scan_one_entity(excel_trust)
        if not entries:
            logger.warning("No indexed accounts found in Box for '%s'.", excel_trust)
            return None

        with self._lock:
            self._index.update(entries)
        self._save_cache(self._index)

        result = self._numeric_search(pdf_digits)
        if result:
            return result

        result = self._local_account_match(entries.values(), pdf_digits)
        if result:
            return result

        if provider:
            provider_tokens = self._tokens(provider)
            unique = {(e.entity, e.account_subfolder): e for e in entries.values()}.values()
            candidates = [e for e in unique if provider_tokens & self._tokens(e.account_subfolder)]
            if len(candidates) == 1:
                return candidates[0]

        if len(entries) == 1:
            return next(iter(entries.values()))

        logger.warning(
            "Excel matched trust '%s' but the exact account folder could not be confirmed "
            "(%d candidate folders) — skipping to avoid a wrong upload.",
            excel_trust, len(entries),
        )
        return None

    def _boot(self) -> None:
        self._refresh_excel()
        cached = self._load_cache()
        if cached is not None and not self._is_stale():
            with self._lock:
                self._index = cached
            logger.info("Index loaded from cache: %d accounts", len(self._index))
        else:
            self._rebuild(refresh_excel=False)

    def _rebuild(self, refresh_excel: bool = True) -> None:
        if not self._rebuild_lock.acquire(blocking=False):
            self._rebuild_lock.acquire()
            self._rebuild_lock.release()
            return
        try:
            logger.info("Rebuilding Box index and refreshing Excel from Box...")
            if refresh_excel:
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
