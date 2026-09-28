"""Launch the app and model service as separate, automatically connected processes."""

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
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
    project_dir = Path(__file__).resolve().parent
    load_dotenv(project_dir / ".env", override=False)
    environment = os.environ.copy()
    host = environment.get("VOXBENCH_MODEL_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "Shared local mode requires a loopback VOXBENCH_MODEL_HOST. "
            "Use the model-only launcher for remote hosting."
        )
    port = int(environment.get("VOXBENCH_MODEL_PORT", "7861"))
    api_key = environment.get("VOXBENCH_MODEL_API_KEY") or secrets.token_urlsafe(32)
    model_url = f"http://127.0.0.1:{port}"
    environment.update(
        {
            "VOXBENCH_MODEL_API_KEY": api_key,
            "VOXBENCH_MODEL_URL": model_url,
            "VOXBENCH_INFERENCE_MODE": "service",
        }
    )

    model = subprocess.Popen(
        [sys.executable, str(project_dir / "model_server.py")],
        env=environment,
        cwd=project_dir,
    )
    app: subprocess.Popen | None = None
    try:
        client = VoxBenchModelClient(model_url, api_key, timeout=2)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if model.poll() is not None:
                raise SystemExit(
                    f"The model service exited during startup with code {model.returncode}."
                )
            try:
                client.health()
                break
            except InferenceError:
                time.sleep(0.25)
        else:
            raise SystemExit("The model service did not become ready within 120 seconds.")

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
