"""Launch the app and model service as separate, automatically connected processes."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from inference.client import InferenceError, VoxBenchModelClient


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch VoxBench locally.")
    parser.add_argument("model", nargs="?", choices=("nano", "turbo"), default="nano")
    arguments = parser.parse_args()
    project_dir = Path(__file__).resolve().parent
    environment = {
        **os.environ,
        "VOXBENCH_MODEL_HOST": "127.0.0.1",
        "VOXBENCH_MODEL_PORT": "7861",
        "VOXBENCH_MODEL_API_KEY": "",
        "VOXBENCH_MODEL": arguments.model,
        "VOXBENCH_SHARED_LOCAL_MODE": "1",
    }
    model_url = "http://127.0.0.1:7861"

    model = subprocess.Popen(
        [sys.executable, str(project_dir / "model_server.py")],
        env=environment,
        cwd=project_dir,
    )
    app: subprocess.Popen | None = None
    try:
        client = VoxBenchModelClient(model_url, timeout=2)
        while True:
            if model.poll() is not None:
                raise SystemExit(
                    f"The model service exited during startup with code {model.returncode}."
                )
            try:
                client.health()
                break
            except InferenceError:
                time.sleep(0.25)

        print(f"Model service ready at {model_url}")
        app = subprocess.Popen(
            [sys.executable, str(project_dir / "app.py")],
            env=environment,
            cwd=project_dir,
        )
        raise SystemExit(app.wait())
    except KeyboardInterrupt:
        pass
    finally:
        if app is not None:
            _stop(app)
        _stop(model)


if __name__ == "__main__":
    main()
