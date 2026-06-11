import logging
import sys
from pathlib import Path
from src.config import StatementConfig
from src.exceptions import ConfigurationError
from src.box_client import BoxUploader, TokenStore, build_client
from src.box_index_builder import BoxIndexBuilder
from src.live_index import LiveIndex
from src.pdf_parser import PDFParser
from src.processor import StatementProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python batch.py \"C:\\path\\to\\folder\"")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.exists() or not folder.is_dir():
        print(f"Folder not found: {folder}")
        sys.exit(1)

    try:
        config = StatementConfig.from_env()
        config.validate()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    token_store = TokenStore(config.token_file)
    client = build_client(config.box_client_id, config.box_client_secret, token_store)
    builder = BoxIndexBuilder(client)
    index = LiveIndex(builder, config.index_cache_path)
    uploader = BoxUploader(client)
    parser = PDFParser(config.anthropic_api_key)
    processor = StatementProcessor(parser, index, uploader)

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        logger.info("No PDF files found in: %s", folder)
        return

    logger.info("Found %d PDF files in: %s", len(pdfs), folder)

    counts = {"uploaded": 0, "skipped": 0, "failed": 0}

    for i, pdf in enumerate(pdfs, 1):
        logger.info("[%d/%d] %s", i, len(pdfs), pdf.name)
        try:
            result = processor.process(pdf)
        except Exception as exc:
            logger.error("Failed: %s — %s", pdf.name, exc)
            result = "failed"
        counts[result] = counts.get(result, 0) + 1

    logger.info("─" * 50)
    logger.info(
        "Done.  Uploaded: %d  |  Skipped: %d  |  Failed: %d",
        counts["uploaded"], counts["skipped"], counts["failed"],
    )


if __name__ == "__main__":
    main()