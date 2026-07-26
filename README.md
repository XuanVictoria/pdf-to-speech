# PDF to Speech — Web App

A free web version of the [PDF to Speech macOS app](../PDFtoSpeech). Upload a PDF
(or EPUB / text / Markdown), pick a voice, and download a natural-sounding MP3.
Built with Streamlit, designed to run on **Streamlit Community Cloud**.

## Layout

| File | Purpose |
|------|---------|
| `streamlit_app.py` | The web UI (entry point). |
| `core_web.py` | Conversion logic: text extraction, `clean_text`, chunking, synthesis. |
| `requirements.txt` | Dependencies Streamlit Cloud installs on deploy. |
| `.streamlit/config.toml` | Theme and 25 MB upload limit. |
| `assets/app_icon.png` | The app icon (browser tab + Cloud app card). |
| `make_favicon.py` | Regenerates `assets/app_icon.png` from the source artwork. |

## How it differs from the macOS app

The speech quality is identical — same `clean_text()` logic, same Edge neural
voices. The changes are all consequences of running on a shared server:

- **Nothing touches disk.** Uploads are read into memory and discarded; the MP3
  is streamed back through the browser.
- **Long documents are chunked.** Text is split on paragraph/sentence boundaries
  into ~3,000-character pieces, synthesized one at a time, and the MP3 frames are
  concatenated. This drives a real progress bar and avoids one long-lived request.
- **A 60,000-character ceiling** per conversion (about 65 minutes of audio) keeps
  one big book from monopolizing the free container. Longer files are truncated at
  a sentence boundary, with a notice. The macOS app has no limit.
- **A gTTS fallback.** If Microsoft's Edge TTS service refuses the server (it
  occasionally rate-limits datacenter IPs), the app falls back to Google TTS
  instead of failing. Quality is lower and speed/pitch are ignored.
- **EPUB support**, which comes free with PyMuPDF.

### ⚠️ Disclaimer & Privacy Notice

**1. "As-Is" Software Provision**
This application (both the desktop version and web application) is provided "as is" and "as available," without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement. In no event shall the author or copyright holders be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.

**2. Data Privacy & Handling**
* **Desktop Application:** Processes files entirely on your local machine[cite: 1]. No document data, text, or converted audio is transmitted to external servers or stored outside your device[cite: 1].
* **Web Application:** Processes files in temporary server memory solely to generate the requested audio output. Uploaded files and generated audio are automatically and permanently purged upon completion or session termination. No files are retained, logged, or permanently stored.

**3. Third-Party Services**
This tool utilizes public text-to-speech APIs (such as Microsoft Edge TTS) to synthesize voice output[cite: 1]. By using this application, you acknowledge that text chunks are processed via these underlying service endpoints strictly for audio synthesis.

**4. User Responsibility**
Users are solely responsible for ensuring they have the legal right, authorization, or fair-use permission to process, convert, and listen to any PDF or document materials ingested into this application[cite: 1].
