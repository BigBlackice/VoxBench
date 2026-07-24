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

### Optional audio dependencies

The base WebUI uses `requirements.txt`. Helpers for the planned audio-processing
and export features are kept separately in `requirements-audio.txt` so they are
not required for ordinary speech generation.

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
than a Python package. Planned MP3 export, chapter metadata, and advanced audio
processing will detect it at runtime and direct users to the
[official FFmpeg download page](https://ffmpeg.org/download.html) when needed.

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
