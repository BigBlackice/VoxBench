import threading
import unittest

from app_logic.generation_control import GenerationController


class GenerationControllerTests(unittest.TestCase):
    def test_pauses_and_resumes_an_active_job(self):
        controller = GenerationController()
        controller.begin()
        self.assertTrue(controller.pause())

        continued = threading.Event()

        def wait_for_resume():
            controller.wait_if_paused()
            continued.set()

        worker = threading.Thread(target=wait_for_resume)
        worker.start()
        self.assertFalse(continued.wait(0.05))
        self.assertTrue(controller.resume())
        self.assertTrue(continued.wait(1))
        worker.join()
        controller.finish()

    def test_ignores_pause_when_no_job_is_active(self):
        controller = GenerationController()
        self.assertFalse(controller.pause())
        self.assertFalse(controller.resume())


if __name__ == "__main__":
    unittest.main()
