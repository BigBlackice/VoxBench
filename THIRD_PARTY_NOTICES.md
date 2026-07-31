# Third-party notices

VoxBench depends on third-party software that remains subject to its own
license terms. The packages are installed separately by `pip`; their source
code is not copied into this repository.

| Component | License | Project |
| --- | --- | --- |
| Chatterbox TTS | MIT | <https://github.com/resemble-ai/chatterbox> |
| Chatterbox Nano model | MIT | <https://huggingface.co/ResembleAI/chatterbox-nano> |
| Beautiful Soup | MIT | <https://www.crummy.com/software/BeautifulSoup/> |
| FastAPI | MIT | <https://github.com/fastapi/fastapi> |
| Gradio | Apache-2.0 | <https://github.com/gradio-app/gradio> |
| ItsDangerous | BSD-3-Clause | <https://github.com/pallets/itsdangerous> |
| pypdf | BSD-3-Clause | <https://github.com/py-pdf/pypdf> |
| python-docx | MIT | <https://github.com/python-openxml/python-docx> |
| python-dotenv | BSD-3-Clause | <https://github.com/theskumar/python-dotenv> |
| SoundFile | BSD-3-Clause | <https://github.com/bastibe/python-soundfile> |
| Uvicorn | BSD-3-Clause | <https://github.com/Kludex/uvicorn> |

These notices are provided for attribution and convenience. Installed Python
distributions include their applicable license text and metadata.

FFmpeg and FFprobe are optional external programs and are not distributed with
VoxBench. FFmpeg licensing depends on how a particular build was configured;
see <https://ffmpeg.org/legal.html>.

Chatterbox-generated audio includes Resemble AI's PerTh neural watermarking.
VoxBench does not remove or disable that watermark.
