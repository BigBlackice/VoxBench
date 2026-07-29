# Chatterbox Nano Web UI

A local Gradio interface for Resemble AI's Chatterbox-Nano model. The app
automatically selects NVIDIA CUDA, AMD ROCm, or Apple Metal when supported by
the installed PyTorch build, falls back to CPU, and splits long text into
sequential chunks.

## Requirements

- Python 3.11
- Git (used by pip to install the tested Chatterbox revision)
- FFmpeg with FFprobe (optional; required for converted exports and chapter
  assembly)

The virtual environment and downloaded model cache are intentionally local and
excluded from Git. Each operating system creates its own compatible copies.
All required Python packages, including the FastAPI/Uvicorn HTTP stack, are
installed from the baseline `requirements.txt`.

## Reference samples

Uploaded and recorded reference clips are automatically copied into the local
`samples/` folder. Saved samples can be selected again from the WebUI without
uploading them a second time. The folder is excluded from Git because reference
recordings may contain private voice data.

The shared drop area beside the synthesis textbox accepts supported text files
or reference-audio files. Text files populate the synthesis text; audio files
replace the current reference and are saved into `samples/`. Other file types
are rejected.

## Generated output

Generated audio is saved as WAV by default under the local `outputs/` folder
while remaining available through Gradio's existing audio player and download
button. Persistent storage can be disabled, or its destination changed, under
**Advanced options**. Relative output paths are resolved from the project
directory. MP3, M4A, OGG, and WebM export are also available when FFmpeg is
installed. Only the selected format is stored. Generated output is excluded
from Git.

## Chapter assembly

The **Chapter assembly** button opens a standalone interface at `/assemble` in
a new browser tab. It starts in the project's `outputs/` folder. The Browse
button opens the operating system's folder picker, and the file list displays
only supported audio files. Files can be previewed as waveforms or added to an
ordered chapter list.

The assembly interface supports non-destructive start/end trimming, per-file
and batch volume adjustment, a speech equalization preset, reordering, and
configurable silence or crossfade transitions. The default interval is 500 ms.
Final files are saved under `outputs/` by default.

M4B exports contain sequential `Chapter 1`, `Chapter 2`, and later markers that
VLC can display. MP3 exports contain ID3 chapter metadata, but VLC does not
currently read MP3 `CHAP` frames. WAV export is available as a lossless
alternative, but WAV does not reliably support embedded chapter markers.

FFmpeg and FFprobe are required for this interface. If they are unavailable,
its controls are disabled and the interface links to the
[official FFmpeg download page](https://ffmpeg.org/download.html).

### Optional FFmpeg support

FFmpeg is the only optional component and is an external executable rather than
a Python package. FFprobe is normally included with FFmpeg. The application
detects both at startup; no automated download or installation is performed.

Without FFmpeg, WAV synthesis and the main WebUI remain available, while
converted exports and chapter assembly are disabled. The interface links to the
[official FFmpeg download page](https://ffmpeg.org/download.html).

## Document workspace

The **Document workspace** button opens `/doc/` in a new browser tab. PDF and
EPUB files are imported into local projects under `documents/`, which is
excluded from Git.

The document viewer itself begins as a PDF/EPUB drag-and-drop or upload area,
then changes into the source viewer after import. **Replace document** deletes
all locally stored document source, extraction, edit, and status data before
returning the same panel to upload mode. Generated files under `outputs/` are
not deleted. This keeps at most one imported document in project storage. The
workspace places an editable text section beside its original PDF page or EPUB
chapter. It provides section navigation, autosave, renaming, reordering,
duplication, removal, merging, cursor-based splitting, search and replace,
reversible cleanup, and restoration of the originally extracted text. PDF
pages become initial sections; EPUB spine chapters retain their natural order.
OCR is not performed.

The synthesis section beneath the editor can generate the current section,
checked sections, or the entire document. Documents are processed one section
at a time and use the existing automatic text chunking within each section.
Whole-document synthesis first applies every cleanup operation, removes
repeated headers and footers, and skips sections with no remaining text.
Generated WAV chapters are saved under `outputs/`, remain linked to their
source sections, and can be opened directly in Chapter assembly.

## Run on Windows

Double-click `run.bat`, or run it from Command Prompt:

```bat
run.bat
```

The batch launcher does not require changing the PowerShell execution policy.

## Run on Linux or macOS

```sh
chmod +x run.sh
./run.sh
```

Both launchers create `.venv` with Python 3.11 when needed, install the pinned
dependencies, and start the local interface. Model weights are downloaded to
`.cache/huggingface` on first launch.

## Shared login and remote access

VoxBench remains local-only by default. Optional shared login and network
access are configured through a private `.env` file in the project directory.
Copy `.env.example` to `.env`; the real `.env` is excluded from Git.

Generate a password hash without storing the plain-text password:

```bat
.venv\Scripts\python.exe -m webui.auth hash-password
```

On Linux or macOS:

```sh
.venv/bin/python -m webui.auth hash-password
```

Paste the result into `VOXBENCH_PASSWORD_HASH`. Generate the independent
session-signing secret with:

```bat
.venv\Scripts\python.exe -m webui.auth generate-secret
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

Authentication protects the main synthesizer, document workspace, chapter
assembly, Gradio APIs and queues, uploaded/generated media, document sources,
and download routes with one signed login session.

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
