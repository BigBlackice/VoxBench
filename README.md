# VoxBench

VoxBench is a self-hosted workspace for turning documents or pasted text into
speech and complete audiobooks with Resemble AI's Chatterbox Nano model. The
single-page NiceGUI application and model run as separate services, even on one
machine. The model service selects
NVIDIA CUDA, AMD ROCm, or Apple Metal when supported by PyTorch, falls back to
CPU, and returns generated audio to the application for local processing.

VoxBench is an independent project and is not affiliated with or endorsed by
Resemble AI.

## Requirements

- Python 3.11
- Git (used by pip to install the tested Chatterbox revision)
- FFmpeg with FFprobe (optional; required for converted exports and chapter
  assembly)

The virtual environment and downloaded model cache are intentionally local and
excluded from Git. Each operating system creates its own compatible copies.
The shared installation uses `requirements.txt`. Application-only and
model-only installations use their respective requirement files and virtual
environments, so an application host does not need PyTorch or Chatterbox.

## Install and run

Clone the repository:

```sh
git clone https://github.com/BigBlackice/VoxBench.git
cd VoxBench
```

On Windows, double-click `run.bat` or run it from Command Prompt:

```bat
run.bat
```

On Linux or macOS:

```sh
chmod +x run.sh
./run.sh
```

Both launchers create a local `.venv` using Python 3.11 when needed and install
the pinned dependencies. They start the model service on `127.0.0.1:7861`, wait
for it to become ready, then start the application at
<http://127.0.0.1:7860>. The two processes are connected automatically. Model
weights are downloaded to `.cache/huggingface` on first synthesis.

### Deployment modes

The normal `run.bat` or `run.sh` command is the shared local deployment. It
still uses the split architecture but manages both processes as one convenient
launch. Closing it stops both services. Shared local mode always connects the
application to its own local service at `127.0.0.1:7861`; use `run-app.*` when
you want the saved connection settings to target a remote model service.

To host only the model service, use `run-model.bat` or `run-model.sh`. This uses
`.venv-model` and installs `requirements-model.txt`. For access from another
machine, configure a private `.env` on the model host:

```dotenv
VOXBENCH_MODEL_HOST=0.0.0.0
VOXBENCH_MODEL_PORT=7861
VOXBENCH_MODEL_API_KEY=a-long-random-secret
```

The service refuses non-loopback binding without an API key. Use TLS through a
trusted reverse proxy or keep the endpoint on a trusted private network; the
built-in Uvicorn listener does not provide HTTPS.

To run only the application, use `run-app.bat` or `run-app.sh`. This creates
`.venv-app`, installs only `requirements-app.txt`, and does not install, load,
or launch Chatterbox or PyTorch. Its initial configuration is written to the
private `voxbench.json` file on first start. Use **Settings → Model
connection** to set a remote model-service URL and API key; the default is
`http://127.0.0.1:7861`. Changes save immediately and persist across restarts.

The application performs document parsing, cleanup, chunking, file storage,
chapter metadata, FFmpeg conversion, and audiobook assembly. The model service
receives only prepared text chunks, synthesis settings, optional reference
audio, and returns WAV audio. Source documents are never sent to it.

The same settings dialog also supports the existing generic hosted-provider
adapter. Provider APIs differ, so a concrete provider may still need a small
adapter for its exact request and response format.

## Reference samples

Place and commit one bundled default voice sample in `sample/` to use it whenever
the user does not upload a reference clip.

Uploaded reference clips are limited to 10 MB. VoxBench keeps only one active
upload per browser session, replaces it when another clip is uploaded, and
removes it when that session ends. The transient `reference_audio/` workspace
is excluded from Git because it may contain private voice data.

## Generated output

Pasted text and documents are saved under the local `outputs/` folder. A
document is processed one prepared page at a time and assembled into a
chaptered M4B by default. The completed file can be played or downloaded
directly from the page. Generated output is excluded from Git.

The application and model service write rotating logs to `logs/app.log` and
`logs/model.log`. Each log retains up to 20 MB across its current file and
three backups.

Use the **Settings** button in the header to select the output type and adjust
seed, sampling values, repetition penalty, chunk length, pause length, and
loudness normalization. M4B is selected by default when FFmpeg and FFprobe are
available. It writes a chapter per current document page. In **Advanced
editing**, PDF bookmarks can instead define output-only chapters without
changing the editable page view; the default includes top-level bookmarks and
their direct children. The default **Skip printed table of contents** option
excludes only pages that strongly match bookmark titles and TOC dot leaders;
those pages remain available in Advanced editing. EPUBs continue to use EPUB 3
navigation or EPUB 2 NCX entries, including anchors inside a content file. WAV
remains available without FFmpeg; MP3, M4A, Ogg, and WebM require FFmpeg.

## Chapter assembly

Document creation requires FFmpeg and FFprobe to assemble the generated
sections and write standard M4B chapter markers that players such as VLC can
display. Audio editing and manual chapter assembly are planned for a later
NiceGUI screen.

### Optional FFmpeg support

FFmpeg is the only optional component and is an external executable rather than
a Python package. FFprobe is normally included with FFmpeg. The application
detects both at startup; no automated download or installation is performed.

Without FFmpeg, pasted-text WAV synthesis remains available. Document-to-
audiobook creation is unavailable until both FFmpeg and FFprobe are installed.

## Document workspace

PDF, EPUB, and DOCX files are imported into local projects under `documents/`,
which is excluded from Git. Uploading a new document replaces the stored
document data but never deletes generated output. The primary flow is simply:
upload a document, optionally add a reference recording, and select **Create
audiobook**. VoxBench removes repeated headers and footers, repairs ordinary
line breaks and hyphenation, skips empty sections, and chunks each section for
generation.

The **Advanced editing** button opens a full-screen dialog with the selected
parsed section and its source side by side. You can review a PDF page (or EPUB/
DOCX source), amend a section title or text, save it, or restore the original
extracted text before generation. OCR is not performed.

## Shared login and remote access

VoxBench remains local-only by default. Optional shared login and network
access are configured through a private `.env` file in the project directory.
Copy `.env.example` to `.env`; the real `.env` is excluded from Git.

Generate a password hash without storing the plain-text password:

```bat
.venv\Scripts\python.exe -m app_logic.auth hash-password
```

On Linux or macOS:

```sh
.venv/bin/python -m app_logic.auth hash-password
```

Paste the result into `VOXBENCH_PASSWORD_HASH`. Generate the independent
session-signing secret with:

```bat
.venv\Scripts\python.exe -m app_logic.auth generate-secret
```

Then configure `.env`:

```dotenv
VOXBENCH_AUTH_ENABLED=true
VOXBENCH_REMOTE_ACCESS=true
VOXBENCH_PORT=7860
VOXBENCH_USERNAME=voxbench
VOXBENCH_PASSWORD_HASH=pbkdf2_sha256$...
VOXBENCH_SESSION_SECRET=...
VOXBENCH_COOKIE_SECURE=false
```

Authentication protects the application page, NiceGUI connection, uploaded/
generated media, document sources, and download routes with one signed login
session.

`VOXBENCH_REMOTE_ACCESS=true` changes the bind address from `127.0.0.1` to
`0.0.0.0`. VoxBench refuses to enable remote binding unless authentication is
also enabled and completely configured. Binding to `0.0.0.0` makes the chosen
port reachable from networks permitted by the host firewall and router; it
does not itself provide HTTPS or configure DDNS/port forwarding.

For internet-facing access, place VoxBench behind an HTTPS reverse proxy and
restrict access with the operating-system firewall and router. Set
`VOXBENCH_COOKIE_SECURE=true` only when clients reach VoxBench through HTTPS.
Do not expose the Uvicorn development server directly to the public internet.
VoxBench listens on only `VOXBENCH_PORT` (7860 by default).

## License

VoxBench is licensed under the [MIT License](LICENSE).

Third-party components retain their own licenses. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and upstream
project links.
