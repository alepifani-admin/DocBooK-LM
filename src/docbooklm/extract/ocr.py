"""OCR delle scansioni con Vision di macOS, in italiano e inglese.

Costa 1-2 secondi per pagina su CPU: resta comunque piu' conveniente che
caricare un modello vision sulla Vega mentre il modello di chat la occupa.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("docbooklm")


def available() -> bool:
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
    except Exception:  # pragma: no cover - dipende dal sistema
        return False
    return True


def recognize(path: Path) -> str:
    """Testo riconosciuto in un'immagine; stringa vuota se Vision non c'e'."""
    if not available():
        return ""
    import Quartz
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        return ""
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return ""

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, {})
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["it-IT", "en-US"])
    request.setUsesLanguageCorrection_(True)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        logger.warning("OCR fallito su %s: %s", path.name, error)
        return ""

    lines: list[str] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(candidates[0].string())
    return "\n".join(lines)
