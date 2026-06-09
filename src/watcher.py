import os
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from src.processor import StatementProcessor

logger = logging.getLogger(__name__)

class DownloadWatcher:
    def __init__(self, folder: Path, processor: StatementProcessor) -> None:
        self._folder = folder
        self._processor = processor

    def start(self) -> None:
        seen: set[str] = set()
        handler = _PDFEventHandler(self._processor, seen)
        observer = Observer()
        observer.schedule(handler, str(self._folder), recursive=False)
        observer.start()
        logger.info("Watching: %s", self._folder)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            logger.info("Watcher stopped.")

class _PDFEventHandler(FileSystemEventHandler):
    _STABLE_TIMEOUT = 60

    def __init__(self, processor: StatementProcessor, seen: set[str]) -> None:
        self._processor = processor
        self._seen = seen

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.dest_path)

    def _handle(self, path: str) -> None:
        if not path.lower().endswith(".pdf") or path in self._seen:
            return
        self._seen.add(path)
        if self._wait_stable(path):
            self._processor.process(Path(path))
        else:
            logger.warning("Download timed out: %s", os.path.basename(path))

    def _wait_stable(self, path: str) -> bool:
        prev = -1
        for _ in range(self._STABLE_TIMEOUT):
            try:
                size = os.path.getsize(path)
                if size > 0 and size == prev:
                    return True
                prev = size
            except OSError:
                pass
            time.sleep(1)
        return False