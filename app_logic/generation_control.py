import threading


class GenerationController:
    """Cooperatively pause the single active synthesis job between chunks."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = False
        self._paused = False
        self._aborted = False
        self._keep_partial = False

    def begin(self) -> None:
        with self._condition:
            self._active = True
            self._paused = False
            self._aborted = False
            self._keep_partial = False

    def finish(self) -> None:
        with self._condition:
            self._active = False
            self._paused = False
            self._aborted = False
            self._keep_partial = False
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

    def abort(self, keep_partial: bool) -> bool:
        with self._condition:
            if not self._active:
                return False
            self._aborted = True
            self._keep_partial = keep_partial
            self._paused = False
            self._condition.notify_all()
            return True

    def is_aborted(self) -> bool:
        with self._condition:
            return self._active and self._aborted

    def keep_partial(self) -> bool:
        with self._condition:
            return self._keep_partial

    def wait_if_paused(self) -> bool:
        """Wait until resumed and report whether the job had been paused."""
        with self._condition:
            was_paused = self._active and self._paused
            while self._active and self._paused and not self._aborted:
                self._condition.wait()
            return was_paused
