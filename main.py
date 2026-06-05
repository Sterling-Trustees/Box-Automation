import logging
import sys
from src.config import StatementConfig
from src.exceptions import ConfigurationError
from src.box_client import BoxUploader, TokenStore, build_client
from src.box_index_builder import BoxIndexBuilder
from src.live_index import LiveIndex
from src.pdf_parser import PDFParser
from src.processor import StatementProcessor
from src.watcher import DownloadWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("boxsdk").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def main() -> None:
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
    logger.info("Index ready: %d Box accounts + %d Excel mappings", len(index), index.excel_len())

    uploader = BoxUploader(client)
    parser = PDFParser(config.anthropic_api_key)
    processor = StatementProcessor(parser, index, uploader)

    DownloadWatcher(config.downloads_folder, processor).start()

if __name__ == "__main__":
    main()
