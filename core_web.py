"""Core PDF/text -> MP3 conversion for the *web* build of PDF to Speech.

This mirrors the validated logic of the macOS app's `core.py` — most importantly
`clean_text()`, which collapses the artificial line breaks a PDF extractor emits
at every visual line wrap (edge-tts reads each newline as a hard pause, which
otherwise makes the narration choppy mid-sentence).

Differences from the desktop version, all forced by running on a server:

* Everything is bytes in / bytes out. Streamlit Community Cloud gives each app an
  ephemeral container, so nothing is written to disk.
* Long documents are split into chunks and synthesized one at a time, then the
  MP3 frames are concatenated. This gives honest progress reporting and avoids
  one very long-lived request to Microsoft's servers.
* A gTTS fallback engine exists, because datacenter IPs are occasionally refused
  by the Edge TTS endpoint and a free public app should degrade instead of die.
"""

from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path
from typing import Callable, Optional

import edge_tts
import pymupdf


DEFAULT_VOICE = "en-US-AvaNeural"

# Curated high-quality English neural voices, so the dropdown works without a
# live voice-list request on every page load. Format: (ShortName, friendly label).
CURATED_VOICES: list[tuple[str, str]] = [
    ("en-US-AvaNeural", "Ava — US English, female (warm, natural)"),
    ("en-US-AndrewNeural", "Andrew — US English, male (warm)"),
    ("en-US-EmmaNeural", "Emma — US English, female (friendly)"),
    ("en-US-BrianNeural", "Brian — US English, male (casual)"),
    ("en-US-JennyNeural", "Jenny — US English, female"),
    ("en-US-GuyNeural", "Guy — US English, male"),
    ("en-US-AriaNeural", "Aria — US English, female"),
    ("en-GB-SoniaNeural", "Sonia — British English, female"),
    ("en-GB-RyanNeural", "Ryan — British English, male"),
    ("en-AU-NatashaNeural", "Natasha — Australian English, female"),
    ("en-AU-WilliamNeural", "William — Australian English, male"),
    ("en-CA-ClaraNeural", "Clara — Canadian English, female"),
    ("en-IN-NeerjaNeural", "Neerja — Indian English, female"),
]

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".epub"}

# Chunk size for synthesis. Small enough that each request finishes quickly (so
# progress moves and nothing times out), large enough that chunk boundaries land
# on paragraph/sentence breaks and stay inaudible.
CHUNK_CHARS = 3000


class ConversionError(Exception):
    """Raised when conversion fails in a way worth showing to the user."""


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #

def clean_text(text: str) -> str:
    """Turn raw PDF text into prose that flows naturally through TTS.

    Collapses the artificial single line breaks inside a paragraph into spaces
    while preserving real paragraph boundaries (blank lines) as a single newline,
    so the voice pauses only between paragraphs, never mid-sentence.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Rejoin words hyphenated across a line break: "informa-\ntion" -> "information".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    paragraphs = re.split(r"\n[ \t]*\n", text)

    cleaned: list[str] = []
    for para in paragraphs:
        para = re.sub(r"\s*\n\s*", " ", para)
        para = re.sub(r"[ \t]+", " ", para).strip()
        if para:
            cleaned.append(para)

    return "\n".join(cleaned)


def extract_text(data: bytes, filename: str) -> str:
    """Extract and clean the text of an uploaded document, entirely in memory."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ConversionError(
            f"Unsupported file type: {suffix or '(none)'}. "
            "Upload a .pdf, .txt, .md, or .epub file."
        )

    if suffix in {".txt", ".md"}:
        return clean_text(data.decode("utf-8", errors="replace"))

    filetype = "pdf" if suffix == ".pdf" else "epub"
    try:
        with pymupdf.open(stream=data, filetype=filetype) as doc:
            if doc.needs_pass:
                raise ConversionError(
                    "This PDF is password-protected, so its text can't be read."
                )
            parts = [page.get_text("text") for page in doc]
    except ConversionError:
        raise
    except Exception as e:  # noqa: BLE001 — surface a readable message to the user
        raise ConversionError(f"Could not read this file: {e}") from e

    return clean_text("\n".join(parts))


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #

def _split_paragraph(para: str, max_chars: int) -> list[str]:
    """Break an oversized paragraph on sentence boundaries (then on spaces)."""
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?;:])\s+", para):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)

    out: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > max_chars:
            out.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    return out


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Split cleaned text into synthesis-sized chunks along natural boundaries."""
    units: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(_split_paragraph(para, max_chars))

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        if current and size + len(unit) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(unit)
        size += len(unit) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


# --------------------------------------------------------------------------- #
# Synthesis — Edge neural voices (primary)
# --------------------------------------------------------------------------- #

async def _synthesize_chunk(text: str, voice: str, rate: str, pitch: str) -> bytes:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


async def _synthesize_chunk_with_retry(
    text: str, voice: str, rate: str, pitch: str, attempts: int = 3
) -> bytes:
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            data = await _synthesize_chunk(text, voice, rate, pitch)
            if data:
                return data
            last_error = ConversionError("The speech service returned empty audio.")
        except Exception as e:  # noqa: BLE001 — transient network/service errors
            last_error = e
        if attempt < attempts - 1:
            await asyncio.sleep(1.5 * (attempt + 1))
    raise ConversionError(
        f"The Edge speech service could not be reached ({last_error})."
    )


def synthesize_edge(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    progress: Optional[Callable[[int, int], None]] = None,
    max_chars: int = CHUNK_CHARS,
) -> bytes:
    """Synthesize `text` to MP3 bytes with Microsoft Edge's neural voices.

    `progress(done_chunks, total_chunks)` is called after each chunk completes.
    """
    chunks = chunk_text(text, max_chars)
    if not chunks:
        raise ConversionError("There is no text to read.")

    async def run() -> bytes:
        out = bytearray()
        for i, chunk in enumerate(chunks, start=1):
            out += await _synthesize_chunk_with_retry(chunk, voice, rate, pitch)
            if progress:
                progress(i, len(chunks))
        return bytes(out)

    return asyncio.run(run())


# --------------------------------------------------------------------------- #
# Synthesis — gTTS (fallback)
# --------------------------------------------------------------------------- #

# Google Translate's TTS has no named voices; the accent comes from the domain.
_GTTS_TLD_BY_LOCALE = {
    "en-US": "com",
    "en-GB": "co.uk",
    "en-AU": "com.au",
    "en-CA": "ca",
    "en-IN": "co.in",
}


def synthesize_gtts(
    text: str,
    voice: str = DEFAULT_VOICE,
    progress: Optional[Callable[[int, int], None]] = None,
    max_chars: int = CHUNK_CHARS,
) -> bytes:
    """Fallback synthesis via gTTS. One voice per accent, no rate/pitch control."""
    try:
        from gtts import gTTS
    except ImportError as e:  # pragma: no cover - only if requirements are trimmed
        raise ConversionError(
            "The fallback voice engine (gTTS) is not installed."
        ) from e

    chunks = chunk_text(text, max_chars)
    if not chunks:
        raise ConversionError("There is no text to read.")

    locale = "-".join(voice.split("-")[:2])
    tld = _GTTS_TLD_BY_LOCALE.get(locale, "com")

    out = bytearray()
    for i, chunk in enumerate(chunks, start=1):
        buf = io.BytesIO()
        try:
            gTTS(text=chunk, lang="en", tld=tld).write_to_fp(buf)
        except Exception as e:  # noqa: BLE001
            raise ConversionError(f"The fallback voice engine failed ({e}).") from e
        out += buf.getvalue()
        if progress:
            progress(i, len(chunks))

    if not out:
        raise ConversionError("The fallback voice engine returned no audio.")
    return bytes(out)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    engine: str = "edge",
    progress: Optional[Callable[[int, int], None]] = None,
    on_fallback: Optional[Callable[[str], None]] = None,
) -> tuple[bytes, str]:
    """Convert text to MP3 bytes. Returns (audio, engine_actually_used).

    With `engine="edge"` (the default) a failure of the Edge service falls back to
    gTTS rather than failing outright, so the public app keeps working even if
    Microsoft refuses the server's IP. `on_fallback(reason)` is called first.
    """
    if not text.strip():
        raise ConversionError("No text could be extracted from this file.")

    if engine == "gtts":
        return synthesize_gtts(text, voice=voice, progress=progress), "gtts"

    try:
        return synthesize_edge(text, voice, rate, pitch, progress=progress), "edge"
    except ConversionError as e:
        if on_fallback:
            on_fallback(str(e))
        return synthesize_gtts(text, voice=voice, progress=progress), "gtts"


def estimate_minutes(text: str, rate_percent: int = 0) -> float:
    """Rough spoken length, for setting expectations before a long conversion."""
    words = len(text.split())
    wpm = 155 * (1 + rate_percent / 100)
    return words / max(wpm, 1)
