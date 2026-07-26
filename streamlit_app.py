"""PDF to Speech — free web app.

Upload a PDF (or .txt / .md / .epub), pick a voice, get a natural-sounding MP3.
Runs on Streamlit Community Cloud; nothing is written to disk or retained.
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

import core_web as core


APP_NAME = "PDF to Speech"

# The free tier gives one small container per app, and synthesis is roughly
# real-time-ish per chunk. This ceiling keeps a single conversion to a few
# minutes so one long book doesn't hold the app hostage for everyone else.
MAX_CHARS = 60_000

# Resolved relative to this file, not the working directory: Streamlit Cloud runs
# the script from the repo root, so a bare "assets/app_icon.png" is fragile.
# Falls back to an emoji if the asset is ever missing, so the app still starts.
ICON_PATH = Path(__file__).parent / "assets" / "app_icon.png"
PAGE_ICON = str(ICON_PATH) if ICON_PATH.is_file() else "🎧"

st.set_page_config(
    page_title=APP_NAME,
    page_icon=PAGE_ICON,
    layout="centered",
    menu_items={"about": f"{APP_NAME} — turn documents into natural-sounding audio."},
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False, max_entries=8)
def extract_cached(data: bytes, filename: str) -> str:
    """Cached so changing the voice/speed doesn't re-parse the PDF."""
    return core.extract_text(data, filename)


def format_duration(minutes: float) -> str:
    total_seconds = int(minutes * 60)
    if total_seconds < 60:
        return f"{total_seconds}s"
    return f"{total_seconds // 60}m {total_seconds % 60:02d}s"


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("Settings")

    voice_labels = [label for _, label in core.CURATED_VOICES]
    voice_by_label = {label: short for short, label in core.CURATED_VOICES}
    default_index = next(
        i for i, (short, _) in enumerate(core.CURATED_VOICES) if short == core.DEFAULT_VOICE
    )
    voice_label = st.selectbox("Voice", voice_labels, index=default_index)
    voice = voice_by_label[voice_label]

    rate_percent = st.slider("Speed", -50, 50, 0, step=5, format="%+d%%")
    pitch_hz = st.slider("Pitch", -20, 20, 0, step=1, format="%+dHz")

    with st.expander("Advanced"):
        engine_choice = st.radio(
            "Voice engine",
            ["Edge neural voices (best quality)", "Google TTS (fallback)"],
            index=0,
            help=(
                "Edge neural voices sound the most natural. If Microsoft's service "
                "is unreachable from the server, the app falls back to Google TTS "
                "automatically — Google TTS ignores the speed and pitch settings."
            ),
        )
        engine = "edge" if engine_choice.startswith("Edge") else "gtts"

    st.divider()
    st.caption(
        "Your file is processed in memory and discarded when the page closes — "
        "nothing is stored on the server."
    )
    st.caption(
        "Speech is synthesized by Microsoft's Edge TTS service (or Google TTS as a "
        "fallback), so an upload leaves this server as text for that request only."
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

if ICON_PATH.is_file():
    # Columns rather than the emoji, so the header carries the app's own artwork.
    # They stack on narrow screens, which degrades acceptably to icon-above-title.
    # A fixed width, not "stretch": on a phone these columns stack, and a
    # stretched icon would fill the whole screen. 72px is sized to just fit the
    # 1:8 column so little slack opens up between the icon and the title.
    icon_col, title_col = st.columns([1, 8], vertical_alignment="center")
    icon_col.image(str(ICON_PATH), width=72)
    title_col.title(APP_NAME)
else:
    st.title(APP_NAME)

st.markdown(
    "Turn a PDF, EPUB, or text file into a natural-sounding MP3 you can listen to "
    "anywhere. Free, no sign-up."
)

uploaded = st.file_uploader(
    "Choose a document",
    type=["pdf", "txt", "md", "epub"],
    help="PDF, EPUB, plain text, or Markdown. Up to 25 MB.",
)

if uploaded is None:
    st.info("Upload a file to get started.")
    with st.expander("Also available as a macOS app"):
        st.markdown(
            "This web version does the same thing as the desktop app, without an "
            "install. The macOS app additionally works on files already on your Mac "
            "via drag-and-drop."
        )
    st.stop()

file_bytes = uploaded.getvalue()

# Uploading a different file must not leave the previous conversion on screen —
# otherwise the download button hands back audio for the wrong document.
source_id = f"{uploaded.name}:{len(file_bytes)}"
if st.session_state.get("source_id") != source_id:
    for key in ("audio", "audio_name", "engine_used", "elapsed", "voice_used"):
        st.session_state.pop(key, None)
    st.session_state["source_id"] = source_id

try:
    text = extract_cached(file_bytes, uploaded.name)
except core.ConversionError as e:
    st.error(str(e))
    st.stop()

if not text.strip():
    st.error(
        "No text could be extracted from this file. If it's a scanned PDF, the pages "
        "are images rather than text — this app can't read those."
    )
    st.stop()

# --- Length handling ------------------------------------------------------- #

truncated = len(text) > MAX_CHARS
if truncated:
    st.warning(
        f"This document is {len(text):,} characters. To keep the free app responsive "
        f"for everyone, only the first {MAX_CHARS:,} characters will be converted. "
        "For the whole document, use the macOS app or split the PDF."
    )
    text_to_read = text[:MAX_CHARS]
    # Trim back to the last sentence end so the audio doesn't stop mid-word.
    cut = max(text_to_read.rfind(". "), text_to_read.rfind("\n"))
    if cut > MAX_CHARS // 2:
        text_to_read = text_to_read[: cut + 1]
else:
    text_to_read = text

words = len(text_to_read.split())
estimate = core.estimate_minutes(text_to_read, rate_percent)

col1, col2, col3 = st.columns(3)
col1.metric("Words", f"{words:,}")
col2.metric("Characters", f"{len(text_to_read):,}")
col3.metric("Approx. audio", format_duration(estimate))

with st.expander("Preview & edit the extracted text"):
    st.caption(
        "Edit this if the PDF picked up headers, footers, or page numbers you'd "
        "rather not hear. The audio is generated from exactly this text."
    )
    # Keyed per file so edits survive a rerun but reset for a new upload.
    text_to_read = st.text_area(
        "Text to read",
        value=text_to_read,
        height=260,
        label_visibility="collapsed",
        key=f"text::{source_id}",
    )

st.divider()

convert = st.button(
    "🎙️ Convert to MP3",
    type="primary",
    use_container_width=True,
    disabled=not text_to_read.strip(),
)

# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #

if convert:
    progress_bar = st.progress(0.0, text="Preparing…")
    status = st.empty()
    started = time.monotonic()

    def on_progress(done: int, total: int) -> None:
        progress_bar.progress(done / total, text=f"Synthesizing… part {done} of {total}")

    def on_fallback(reason: str) -> None:
        status.warning(
            f"Edge voices are unavailable right now ({reason}) — "
            "switching to the Google TTS fallback."
        )

    try:
        audio, engine_used = core.synthesize(
            text_to_read,
            voice=voice,
            rate=f"{rate_percent:+d}%",
            pitch=f"{pitch_hz:+d}Hz",
            engine=engine,
            progress=on_progress,
            on_fallback=on_fallback,
        )
    except core.ConversionError as e:
        progress_bar.empty()
        st.error(str(e))
        st.stop()
    except Exception as e:  # noqa: BLE001 — never show a raw traceback to visitors
        progress_bar.empty()
        st.error(f"Unexpected error: {e}")
        st.stop()

    progress_bar.empty()
    st.session_state["audio"] = audio
    st.session_state["audio_name"] = Path(uploaded.name).with_suffix(".mp3").name
    st.session_state["engine_used"] = engine_used
    st.session_state["elapsed"] = time.monotonic() - started
    st.session_state["voice_used"] = voice_label.split(" — ")[0]

if "audio" in st.session_state:
    audio = st.session_state["audio"]
    engine_used = st.session_state.get("engine_used", "edge")
    elapsed = st.session_state.get("elapsed", 0.0)

    st.success(
        f"Done in {format_duration(elapsed / 60)} · "
        f"{st.session_state.get('voice_used', 'Voice')} · "
        f"{len(audio) / 1_048_576:.1f} MB"
        + (" · Google TTS fallback" if engine_used == "gtts" else "")
    )
    st.audio(audio, format="audio/mp3")
    st.download_button(
        "⬇️ Download MP3",
        data=audio,
        file_name=st.session_state.get("audio_name", "speech.mp3"),
        mime="audio/mpeg",
        type="primary",
        use_container_width=True,
    )
