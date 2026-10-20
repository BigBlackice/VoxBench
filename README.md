# VoxBench

VoxBench is a self-hosted workspace that turns pasted text, PDFs, EPUBs, and
DOCX files into speech and audiobooks using Resemble AI's Chatterbox Nano or
Turbo models. It includes document cleanup, optional voice references, chaptered
M4B output, and an advanced document editor.

VoxBench is independent and not affiliated with Resemble AI.

## Requirements

- Python 3.11
- Git
- FFmpeg with FFprobe for document audiobooks and non-WAV exports

## Quick start

```sh
git clone https://github.com/BigBlackice/VoxBench.git
cd VoxBench
```

On Windows:

```bat
run.bat
```

On Linux or macOS:

```sh
chmod +x run.sh
./run.sh
```

The default launch starts both services; VoxBench is available at
<http://127.0.0.1:7860>. Nano is the default model. Use Turbo with
`run.bat turbo` or `./run.sh turbo`.

The selected model downloads and loads during its first launch. Turbo uses more
memory than Nano.

## Deployment modes

| Command | Purpose |
| --- | --- |
| `run.bat` / `./run.sh` | Application and local model service together |
| `run-model.bat` / `./run-model.sh` | Model service only |
| `run-app.bat` / `./run-app.sh` | Application only; connect it to a remote service in Settings |

Append `turbo` to `run` or `run-model` to select Chatterbox Turbo. Otherwise,
Nano is used. The standalone model service listens on `127.0.0.1:7861` by
default; model-connection settings are saved in the local `voxbench.json`.

For a remote model service, copy `.env.example` to `.env`, set a model API key,
and configure the application’s **Settings → Model connection**. The model
service refuses a non-local bind without an API key.

## Using VoxBench

Upload a document or paste text, optionally upload a reference voice sample,
then select **Create audiobook**. Output defaults to chaptered M4B and is saved
under `outputs/`. Use **Settings** for output format, narration speed, chunking,
seed, and sampling controls. **Advanced editing** lets you review and amend
parsed document text before generation.

Document and uploaded voice data remain local. Generated audio, imported
documents, virtual environments, model caches, logs, and private configuration
are excluded from Git.

## Remote access

VoxBench is local-only by default. To expose the application, enable and fully
configure authentication in `.env` before setting `VOXBENCH_REMOTE_ACCESS=true`.
Use an HTTPS reverse proxy and normal firewall/router controls for internet
access; do not expose the built-in Uvicorn server directly to the public
internet.

Generate credentials with the project virtual environment:

```sh
python -m app_logic.auth hash-password
python -m app_logic.auth generate-secret
```

## License

VoxBench is licensed under the [MIT License](LICENSE). Third-party attribution
is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
