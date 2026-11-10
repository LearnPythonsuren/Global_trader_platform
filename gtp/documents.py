"""Reading earnings-call documents: concall transcript PDFs and call audio.

Companies publish earnings-call material to the exchanges as PDF filings
(transcripts, investor presentations) and audio recordings. This module turns
one of those attachment URLs into text:

* PDF  -> text extracted with pypdf.
* audio -> a transcript from a configured speech-to-text service
  (any OpenAI-compatible ``/audio/transcriptions`` endpoint).

Every network fetch goes through :class:`gtp.net.SafeFetcher`, so only
allowlisted exchange/vendor hosts can ever be reached. Credentials for the
transcription service are read from the environment and never returned to a
caller.
"""

from __future__ import annotations

import io
import os
from typing import Any

import httpx

from .net import FetchError, FetchNotAllowed, SafeFetcher

AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".webm", ".mp4")
PDF_MAGIC = b"%PDF-"


def classify(url: str, kind: str | None = None) -> str:
    if kind in ("pdf", "audio"):
        return kind
    low = url.lower().split("?")[0]
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith(AUDIO_EXT):
        return "audio"
    return "pdf"           # exchange attachments are overwhelmingly PDFs


def extract_pdf(data: bytes, *, max_pages: int = 60, max_chars: int = 200_000) -> dict[str, Any]:
    from pypdf import PdfReader

    if not data.startswith(PDF_MAGIC):
        raise FetchError("The fetched file is not a PDF")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                raise FetchError("The PDF is password protected") from None
        pages = len(reader.pages)
        parts = []
        for page in reader.pages[:max_pages]:
            parts.append(page.extract_text() or "")
            if sum(len(p) for p in parts) > max_chars:
                break
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001 - any malformed PDF becomes a clean error
        raise FetchError(f"Could not read the PDF: {e}") from None
    text = "\n\n".join(p.strip() for p in parts if p.strip())
    return {"pages": pages, "pages_read": min(pages, max_pages), "chars": len(text),
            "truncated": pages > max_pages or len(text) >= max_chars, "text": text}


class DocumentService:
    """Fetches and reads documents in live mode."""

    demo = False

    def __init__(self, fetcher: SafeFetcher, *, transcribe_url: str = "", transcribe_key: str = "",
                 transcribe_model: str = "whisper-1", timeout: float = 120.0, transcribe_transport=None):
        self.fetcher = fetcher
        self.transcribe_url = transcribe_url
        self.transcribe_key = transcribe_key
        self.transcribe_model = transcribe_model
        self.timeout = timeout
        self._transcribe_transport = transcribe_transport

    @property
    def transcription_available(self) -> bool:
        return bool(self.transcribe_url and self.transcribe_key)

    def providers(self) -> dict[str, Any]:
        return {"transcription": self.transcription_available, "allowed_hosts": list(self.fetcher.allowed),
                "max_mb": self.fetcher.max_bytes // 1_000_000, "demo": self.demo}

    def read(self, url: str, kind: str | None = None) -> dict[str, Any]:
        kind = classify(url, kind)
        if kind == "audio":
            return self.transcribe(url)
        ctype, data = self.fetcher.fetch(url, accept=("pdf", "octet-stream"))
        return {"kind": "pdf", "source": url, "content_type": ctype, **extract_pdf(data)}

    def transcribe(self, url: str) -> dict[str, Any]:
        if not self.transcription_available:
            # Validate the URL anyway so the client gets a safe, playable link.
            self.fetcher.check(url)
            return {"kind": "audio", "source": url, "available": False,
                    "message": "Audio transcription is not configured on this server. "
                               "Set GTP_TRANSCRIBE_URL and GTP_TRANSCRIBE_KEY to enable it."}
        ctype, data = self.fetcher.fetch(url)
        filename = url.split("/")[-1].split("?")[0] or "audio.mp3"
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transcribe_transport) as client:
                resp = client.post(
                    self.transcribe_url,
                    headers={"Authorization": f"Bearer {self.transcribe_key}"},
                    files={"file": (filename, data, ctype or "application/octet-stream")},
                    data={"model": self.transcribe_model, "response_format": "json"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as e:
            raise FetchError(f"Transcription service error: {e}") from None
        transcript = body.get("text") if isinstance(body, dict) else None
        return {"kind": "audio", "source": url, "available": True, "transcript": transcript or "",
                "provider": httpx.URL(self.transcribe_url).host, "model": self.transcribe_model}


class DemoDocuments:
    """Serves synthetic earnings-call documents so the feature works offline."""

    demo = True

    def __init__(self):
        self.fetcher = type("F", (), {"allowed": ("demo.gtp.local",), "max_bytes": 30_000_000})()

    @property
    def transcription_available(self) -> bool:
        return True

    def providers(self) -> dict[str, Any]:
        return {"transcription": True, "allowed_hosts": ["demo.gtp.local"], "max_mb": 30, "demo": True}

    def _check(self, url: str) -> None:
        from urllib.parse import urlparse
        p = urlparse(url)
        if p.scheme != "https" or (p.hostname or "") != "demo.gtp.local":
            raise FetchNotAllowed("Demo mode only reads its own synthetic documents (host demo.gtp.local)")

    def read(self, url: str, kind: str | None = None) -> dict[str, Any]:
        from .gdf.demo import demo_document
        self._check(url)
        return demo_document(url, classify(url, kind))

    def transcribe(self, url: str) -> dict[str, Any]:
        return self.read(url, "audio")


def build_documents(settings) -> DocumentService | DemoDocuments:
    if settings.demo:
        return DemoDocuments()
    fetcher = SafeFetcher(tuple(settings.doc_allowed_hosts), max_bytes=settings.doc_max_bytes)
    return DocumentService(fetcher, transcribe_url=settings.transcribe_url, transcribe_key=settings.transcribe_key,
                           transcribe_model=settings.transcribe_model)


# Convenience for scripts/tests.
def env_documents() -> DocumentService:  # pragma: no cover - thin wrapper
    hosts = tuple(h for h in os.environ.get("GTP_DOC_ALLOWED_HOSTS", "").split(",") if h) or None
    fetcher = SafeFetcher(hosts) if hosts else SafeFetcher()
    return DocumentService(fetcher, transcribe_url=os.environ.get("GTP_TRANSCRIBE_URL", ""),
                           transcribe_key=os.environ.get("GTP_TRANSCRIBE_KEY", ""))
