import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def convert_doc_to_markdown_sync(
    path: str,
    cancel_event: threading.Event | None = None,
    **_kwargs: Any,
) -> str:
    """Synchronous CPU worker to convert rich documents to markdown."""
    import tools.read as read_pkg

    cached = read_pkg.get_cached_doc_markdown(path)
    if cached is not None:
        return cached

    def _interrupted() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    if _interrupted():
        return ""

    result_text = None

    try:
        from core.infrastructure.converter import convert_file

        result_text = convert_file(path)
    except Exception as exc:
        logger.debug("Built-in document converter error for %s: %s", path, exc)

    if _interrupted():
        return ""
    if result_text is not None:
        if result_text.strip():
            read_pkg.set_cached_doc_markdown(path, result_text)
        return result_text

    raise RuntimeError(f"Unable to convert '{path}' to markdown.")
