import base64
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf

from inference.client import GenericProviderClient, VoxBenchModelClient
from inference.contract import SynthesisRequest


def wav_bytes() -> bytes:
    output = io.BytesIO()
    sf.write(output, np.zeros(240, dtype=np.float32), 24_000, format="WAV")
    return output.getvalue()


class InferenceHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer test-key":
            self.send_error(401)
            return
        if self.path.endswith("/health"):
            body = {"status": "ok", "api_version": "1"}
        else:
            body = {"api_version": "1", "sample_rate": 24_000}
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.requests.append((self.path, payload, self.headers.get("Authorization")))
        audio = wav_bytes()
        if self.path == "/provider":
            encoded = json.dumps({"audio": base64.b64encode(audio).decode()}).encode()
            content_type = "application/json"
        else:
            encoded = audio
            content_type = "audio/wav"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class InferenceClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        InferenceHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), InferenceHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_voxbench_client_sends_reference_audio_and_decodes_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "voice.wav"
            reference.write_bytes(b"reference")
            client = VoxBenchModelClient(self.base_url, "test-key")
            self.assertEqual(client.health()["status"], "ok")
            self.assertEqual(client.capabilities()["sample_rate"], 24_000)
            result = client.synthesize(
                SynthesisRequest("Hello", audio_prompt_path=str(reference), seed=42)
            )

        self.assertEqual(result.sample_rate, 24_000)
        path, payload, authorization = InferenceHandler.requests[-1]
        self.assertEqual(path, "/v1/synthesize")
        self.assertEqual(authorization, "Bearer test-key")
        self.assertEqual(payload["parameters"]["seed"], 42)
        self.assertEqual(
            base64.b64decode(payload["reference_audio"]["data"]), b"reference"
        )

    def test_generic_provider_accepts_base64_audio_response(self):
        client = GenericProviderClient(
            f"{self.base_url}/provider", "test-key", model="hosted-tts"
        )
        result = client.synthesize(SynthesisRequest("Hello provider"))
        self.assertEqual(result.sample_rate, 24_000)
        self.assertEqual(InferenceHandler.requests[-1][1]["model"], "hosted-tts")


if __name__ == "__main__":
    unittest.main()
