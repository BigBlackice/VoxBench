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
