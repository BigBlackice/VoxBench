# Chatterbox Nano Web UI

A local Gradio interface for Resemble AI's Chatterbox-Nano model. The app
automatically selects NVIDIA CUDA, AMD ROCm, or Apple Metal when supported by
the installed PyTorch build, falls back to CPU, and splits long text into
sequential chunks.

## Requirements

- Python 3.11
- Git (used by pip to install the tested Chatterbox revision)

The virtual environment and downloaded model cache are intentionally local and
excluded from Git. Each operating system creates its own compatible copies.

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

### Optional audio dependencies

The base WebUI uses `requirements.txt`. Helpers for planned advanced
audio-processing features are kept separately in `requirements-audio.txt` so
they are not required for ordinary speech generation.

Install the optional audio dependency set with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-audio.txt
```

On Linux or macOS:

```sh
./.venv/bin/python -m pip install -r requirements-audio.txt
```

The optional file includes the base requirements, so it can also be used when
building a fresh environment. FFmpeg itself is an external executable rather
than a Python package. MP3, M4A, OGG, and WebM export detect it at startup;
chapter metadata and advanced audio processing will also use it. When it is
missing, the interface directs users to the
[official FFmpeg download page](https://ffmpeg.org/download.html).

## Run on Windows

```powershell
.\run.ps1
```

If PowerShell script execution is disabled, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

## Run on Linux or macOS

```sh
chmod +x run.sh
./run.sh
```

Both launchers create `.venv` with Python 3.11 when needed, install the pinned
dependencies, and start the local interface. Model weights are downloaded to
`.cache/huggingface` on first launch.
