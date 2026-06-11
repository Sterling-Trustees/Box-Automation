import re
import logging
from pathlib import Path
from src.pdf_parser import PDFParser
from src.box_client import BoxUploader
from src.live_index import LiveIndex
from src.exceptions import StatementError, IndexLookupError

logger = logging.getLogger(__name__)

class StatementProcessor:
    def __init__(self, parser: PDFParser, index: LiveIndex, uploader: BoxUploader) -> None:
        self._parser = parser
        self._index = index
        self._uploader = uploader

    def process(self, pdf_path: Path) -> str:
        logger.info("Detected: %s", pdf_path.name)
        try:
            return self._run(pdf_path)
        except StatementError as exc:
            logger.error("[%s] %s", pdf_path.name, exc)
            return "failed"

    def _run(self, pdf_path: Path) -> str:
        info = self._parser.parse(pdf_path)
        logger.info("Provider=%s  Account=...%s  Date=%s", info.provider, info.account_number[-4:], info.statement_date)

        entry = self._index.lookup(
            info.account_number,
            provider=info.provider,
            trust_name=info.trust_name or "",
            fund_name=info.fund_name or "",
        )
        if not entry:
            raise IndexLookupError(
                f"Account ending ...{info.account_number[-4:]} not found in index. "
                "Index auto-refreshes every 24h. Restart the app to force an immediate rebuild."
            )

        account_id = self._full_account(entry.account_subfolder) or info.account_number
        remote_name = self._safe_name(
            f"{entry.entity} - {info.provider} {account_id} - {info.statement_date}.pdf"
        )
        logger.info("Target: %s / %s / %s / %s / %s", entry.entity, entry.cis_folder, entry.account_subfolder, info.year, remote_name)

        folder_id = self._uploader.find_upload_folder(
            entry.entity, entry.cis_folder, entry.account_subfolder, info.year
        )
        uploaded = self._uploader.upload(folder_id, pdf_path, remote_name)

        if uploaded:
            logger.info("Uploaded: %s", remote_name)
            return "uploaded"
        logger.warning("Already exists, skipped: %s", remote_name)
        return "skipped"

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    @staticmethod
    def _full_account(account_subfolder: str) -> str:
        candidates: list[str] = []

        m = re.search(r"#([\w\-]+)", account_subfolder)
        if m:
            candidates.append(re.sub(r"[^A-Z0-9]", "", m.group(1), flags=re.IGNORECASE))

        for m in re.finditer(r"\(([\d\-]+)\)", account_subfolder):
            candidates.append(re.sub(r"\D", "", m.group(1)))

        for m in re.finditer(r"\d{3,}-\d{3,}", account_subfolder):
            candidates.append(re.sub(r"\D", "", m.group(0)))

        m = re.search(r"([A-Z0-9]*\d[A-Z0-9]*)\s*$", account_subfolder, re.IGNORECASE)
        if m:
            candidates.append(m.group(1))

        def _is_year(s: str) -> bool:
            return len(s) == 4 and s.isdigit() and 2000 <= int(s) <= 2030

        valid = [c for c in candidates if c and len(c) >= 4 and not _is_year(c)]
        return max(valid, key=len) if valid else ""
