"""The document pipeline must be secure (no SSRF) and extract text correctly."""

import httpx
import pytest

from gtp.documents import DocumentService, classify, extract_pdf
from gtp.net import FetchError, FetchNotAllowed, SafeFetcher, host_allowed


def make_pdf(text: str) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


def public_resolver(host, port, **_):
    return [(2, 1, 6, "", ("93.184.216.34", port))]      # a public IP


def private_resolver(host, port, **_):
    return [(2, 1, 6, "", ("169.254.169.254", port))]    # link-local (cloud metadata)


ALLOWED = ("bseindia.com", "nseindia.com")


def test_host_allowlist():
    assert host_allowed("www.bseindia.com", ALLOWED)
    assert host_allowed("bseindia.com", ALLOWED)
    assert not host_allowed("bseindia.com.evil.com", ALLOWED)
    assert not host_allowed("evil.com", ALLOWED)
    assert not host_allowed("notbseindia.com", ALLOWED)


def test_check_rejects_bad_scheme_host_and_private_ip():
    f = SafeFetcher(ALLOWED, resolver=public_resolver)
    with pytest.raises(FetchNotAllowed, match="https"):
        f.check("http://www.bseindia.com/x.pdf")
    with pytest.raises(FetchNotAllowed, match="allowlist"):
        f.check("https://evil.com/x.pdf")
    with pytest.raises(FetchNotAllowed, match="allowlist"):
        f.check("https://bseindia.com.evil.com/x.pdf")
    private = SafeFetcher(ALLOWED, resolver=private_resolver)
    with pytest.raises(FetchNotAllowed, match="non-public"):
        private.check("https://www.bseindia.com/x.pdf")


def test_fetch_refuses_redirects_and_caps_size():
    def handler(req):
        if req.url.path == "/redir.pdf":
            return httpx.Response(302, headers={"location": "https://www.bseindia.com/final.pdf"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-" + b"a" * 5000)
    f = SafeFetcher(ALLOWED, resolver=public_resolver, transport=httpx.MockTransport(handler))
    with pytest.raises(FetchNotAllowed, match="Redirect"):
        f.fetch("https://www.bseindia.com/redir.pdf")
    small = SafeFetcher(ALLOWED, resolver=public_resolver, max_bytes=1000,
                        transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError, match="exceeds"):
        small.fetch("https://www.bseindia.com/big.pdf")


def test_extract_pdf():
    data = make_pdf("Q2 FY27 Earnings Call Transcript\nRevenue grew 12% to Rs 40,000 crore.")
    out = extract_pdf(data)
    assert out["pages"] == 1 and "Earnings Call Transcript" in out["text"] and "12%" in out["text"]
    with pytest.raises(FetchError, match="not a PDF"):
        extract_pdf(b"not a pdf at all")


def test_document_service_reads_pdf_over_mock_network():
    pdf = make_pdf("Transcript of Sep 2026 Earnings Conference Call. Management: margins were stable.")

    def handler(req):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)

    svc = DocumentService(SafeFetcher(ALLOWED, resolver=public_resolver, transport=httpx.MockTransport(handler)))
    out = svc.read("https://www.bseindia.com/xml/transcript.pdf")
    assert out["kind"] == "pdf" and "Earnings Conference Call" in out["text"]


def test_transcription_not_configured_still_validates_host():
    svc = DocumentService(SafeFetcher(ALLOWED, resolver=public_resolver))
    out = svc.read("https://www.nseindia.com/calls/audio.mp3")
    assert out["kind"] == "audio" and out["available"] is False and "not configured" in out["message"]
    with pytest.raises(FetchNotAllowed):
        svc.read("https://evil.com/audio.mp3")


def test_transcription_posts_to_configured_service():
    audio = b"ID3 fake audio bytes"
    captured = {}

    def fetch_handler(req):
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=audio)

    def whisper_handler(req):
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = req.content
        return httpx.Response(200, json={"text": "Welcome to the earnings call. Revenue grew."})

    svc = DocumentService(
        SafeFetcher(ALLOWED, resolver=public_resolver, transport=httpx.MockTransport(fetch_handler)),
        transcribe_url="https://api.example.com/v1/audio/transcriptions", transcribe_key="sk-secret",
        transcribe_transport=httpx.MockTransport(whisper_handler),
    )
    out = svc.transcribe("https://www.nseindia.com/calls/audio.mp3")
    assert out["available"] is True and out["transcript"].startswith("Welcome to the earnings call")
    assert captured["auth"] == "Bearer sk-secret"
    assert b"earnings" not in captured["auth"].encode()      # key only in header, not leaked elsewhere


def test_classify():
    assert classify("https://x/transcript.pdf") == "pdf"
    assert classify("https://x/audio.mp3") == "audio"
    assert classify("https://x/call", "audio") == "audio"
    assert classify("https://x/file") == "pdf"
