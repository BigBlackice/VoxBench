import threading


class GenerationController:
    """Cooperatively pause the single active synthesis job between chunks."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = False
        self._paused = False

    def begin(self) -> None:
        with self._condition:
            self._active = True
            self._paused = False

    def finish(self) -> None:
        with self._condition:
            self._active = False
            self._paused = False
            self._condition.notify_all()

    def pause(self) -> bool:
        with self._condition:
            if not self._active:
                return False
            self._paused = True
            return True

    def resume(self) -> bool:
        with self._condition:
            if not self._active or not self._paused:
                return False
            self._paused = False
            self._condition.notify_all()
            return True

    def is_paused(self) -> bool:
        with self._condition:
            return self._active and self._paused

    def wait_if_paused(self) -> bool:
        """Wait until resumed and report whether the job had been paused."""
        with self._condition:
            was_paused = self._active and self._paused
            while self._active and self._paused:
                self._condition.wait()
            return was_paused
