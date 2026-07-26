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

## Run locally

```bash
cd ..                       # project root
source venv/bin/activate
pip install -r PDFtoSpeech-web/requirements.txt
streamlit run PDFtoSpeech-web/streamlit_app.py
```

Opens at http://localhost:8501.

---

# Deploying to Streamlit Community Cloud

## Step 1 — Create a GitHub repository

Go to <https://github.com/new> and create a repository:

- **Name:** `pdf-to-speech` (or anything you like)
- **Visibility:** **Public** — Community Cloud's free tier allows unlimited public
  apps but only one private app. Public also means people can see the code, which
  is fine here; there are no secrets in it.
- **Do not** tick "Add a README" / .gitignore / license — the repo must start
  empty so the first push isn't rejected.

## Step 2 — Push this folder

The local git repo is already initialised and committed. Add your new GitHub
repo as the remote and push (replace `YOUR-USERNAME`):

```bash
cd /Users/weixuan/projects/audible_converter/PDFtoSpeech-web
git remote add origin https://github.com/YOUR-USERNAME/pdf-to-speech.git
git push -u origin main
```

If GitHub asks for a password, it wants a **personal access token**, not your
account password: <https://github.com/settings/tokens> → *Generate new token
(classic)* → tick the `repo` scope → paste the token as the password. (Installing
GitHub CLI with `brew install gh` and running `gh auth login` avoids this.)

## Step 3 — Deploy

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `YOUR-USERNAME/pdf-to-speech`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
   - **App URL:** pick your subdomain, e.g. `pdf-to-speech` →
     `https://pdf-to-speech.streamlit.app`
4. Optional: **Advanced settings** → set **Python version** to **3.12**
   (3.13 works too, but 3.12 has the widest wheel coverage, so the build is faster
   and less likely to compile anything from source).
5. Click **Deploy**. The first build takes 2–5 minutes while it installs PyMuPDF.

Watch the build log in the right-hand pane. When it finishes you'll see the app.

## Step 4 — Verify

Upload a small PDF and convert it. Confirm the audio plays and downloads.

**If you see a gTTS fallback warning**, Microsoft is refusing the Streamlit
Cloud IP. The app still works, just with a plainer voice. Usually temporary —
try again later. If it's permanent, the options are a paid TTS API key (Azure
Speech, ElevenLabs) stored in Streamlit **Secrets**, or pointing people to the
macOS app for best quality.

## Changing the app icon

The icon shown on the browser tab and on the Streamlit Cloud app card is the
`page_icon` argument to `st.set_page_config()` — there is no icon upload in the
Cloud dashboard. It's set in `streamlit_app.py`:

```python
ICON_PATH = Path(__file__).parent / "assets" / "app_icon.png"
```

To use different artwork:

1. Drop the new image at `assets/source_icon.jpg` (or update `SOURCE_CANDIDATES`
   in `make_favicon.py` to point at it).
2. Run `python make_favicon.py` — it trims the white margin, crops to a square,
   adds transparent rounded corners, and writes a 256×256 `assets/app_icon.png`.
3. Commit **both** the script output and the source image, then push.

Two things that bite people here:

- **The path must be resolved relative to `__file__`.** Streamlit Cloud does not
  run the script from this directory, so a bare `"assets/app_icon.png"` may not
  resolve. Worse, when Streamlit can't load the image it **silently falls back**
  to rendering the string instead of raising — you just get no icon and no error.
- **Favicons are cached hard.** After deploying, hard-refresh
  (<kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>) or open the app in a private
  window. If the Cloud app card still shows the old icon, use
  **Manage app → Reboot** and re-check.

Detail is lost at 32×32 — the lettering in the artwork is not legible at tab size.
That's normal; the distinctive blue/red shape is what identifies it.

## Updating the app after deploy

Community Cloud watches the branch and redeploys automatically:

```bash
git add -A
git commit -m "Describe the change"
git push
```

If a change doesn't show up, use **Manage app → Reboot** in the Streamlit dashboard.

## Free-tier limits worth knowing

| Limit | Value |
|-------|-------|
| Memory | ~1 GB per app (plenty here — a 60k-char job peaks well under it) |
| Apps | Unlimited public, 1 private |
| Sleep | Apps sleep after ~12 hours idle and wake on the next visit (first load is slow) |
| Concurrency | One container; simultaneous visitors share it and queue behind each other |

The app is deliberately single-purpose and stateless, so a sleeping app costs
nothing and a cold start just means waiting a few seconds.

## Privacy note for your users

The sidebar states this, and it is accurate: uploaded files are held in memory
only and never written to disk. Be aware that the extracted **text** is sent to
Microsoft's Edge TTS service (or Google's, on fallback) to be synthesized — that
is inherent to using a free hosted voice service, and worth keeping in the notice
if you edit the copy.
