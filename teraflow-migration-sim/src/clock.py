"""Injectable time: one orbital second per monotonic second in live runs."""
import time


class LiveClock:
    def __init__(self, orbital_start_s: float = 0):
        self.start = time.monotonic()
        self.orbital_start_s = orbital_start_s

    def now(self) -> float:
        return time.monotonic() - self.start

    def orbital(self) -> float:
        return self.orbital_start_s + self.now()

    def sleep(self, duration: float) -> None:
        if duration > 0:
            time.sleep(duration)


class ManualClock:
    def __init__(self, orbital_start_s: float = 0):
        self.elapsed = 0.0
        self.orbital_start_s = orbital_start_s

    def now(self) -> float:
        return self.elapsed

    def orbital(self) -> float:
        return self.orbital_start_s + self.elapsed

    def sleep(self, duration: float) -> None:
        if duration < 0:
            raise ValueError("Cannot reverse time")
        self.elapsed += duration
