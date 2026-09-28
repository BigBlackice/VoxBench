import base64
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import model_server
from inference.contract import AudioResult


class ModelServerTests(unittest.TestCase):
    def setUp(self):
        self.api_key_patch = patch.object(model_server, "MODEL_API_KEY", "")
        self.api_key_patch.start()
        self.client = TestClient(model_server.model_app)

    def tearDown(self):
        self.api_key_patch.stop()

    def test_health_and_capabilities_do_not_load_the_model(self):
        self.assertEqual(self.client.get("/v1/health").json()["status"], "ok")
        capabilities = self.client.get("/v1/capabilities").json()
        self.assertEqual(capabilities["model"], "chatterbox-nano")
        self.assertEqual(capabilities["api_version"], "1")

    def test_synthesis_returns_wav_and_passes_only_prepared_input(self):
        result = AudioResult(24_000, np.zeros(240, dtype=np.float32))
        with patch.object(model_server.runtime, "synthesize", return_value=result) as run:
            response = self.client.post(
                "/v1/synthesize",
                json={
                    "api_version": "1",
                    "text": "Prepared text only",
                    "parameters": {"temperature": 0.5},
                    "reference_audio": {
                        "filename": "sample.wav",
                        "data": base64.b64encode(b"audio").decode(),
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        request = run.call_args.args[0]
        self.assertEqual(request.text, "Prepared text only")
        self.assertEqual(request.temperature, 0.5)
        self.assertTrue(request.audio_prompt_path)

    def test_api_key_protects_model_service(self):
        with patch.object(model_server, "MODEL_API_KEY", "secret"):
            denied = self.client.get("/v1/health")
            allowed = self.client.get(
                "/v1/health", headers={"Authorization": "Bearer secret"}
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
