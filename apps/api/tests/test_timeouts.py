"""Bounded parsing: hard timeouts, daemon threads and the in-flight cap."""

import threading
import time

import pytest

from app import timeouts
from app.timeouts import OperationTimeout, ParserBusy, run_with_timeout


def test_returns_results_and_propagates_errors() -> None:
    assert run_with_timeout(lambda: 21 * 2, 1) == 42

    def broken() -> int:
        raise ValueError("bad pdf")

    with pytest.raises(ValueError, match="bad pdf"):
        run_with_timeout(broken, 1)


def test_timeout_abandons_a_daemon_thread_that_keeps_its_slot_until_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(timeouts, "_slots", threading.BoundedSemaphore(1))
    started = time.monotonic()
    with pytest.raises(OperationTimeout):
        run_with_timeout(lambda: time.sleep(0.6), 0.1)
    assert time.monotonic() - started < 0.5
    stragglers = [thread for thread in threading.enumerate() if thread.name == "bounded-parse"]
    assert stragglers and all(thread.daemon for thread in stragglers)
    # The abandoned parse still holds the only slot, so new work is refused, not queued.
    with pytest.raises(ParserBusy):
        run_with_timeout(lambda: 1, 1)
    time.sleep(0.7)
    assert run_with_timeout(lambda: 1, 1) == 1


def test_busy_when_every_slot_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    monkeypatch.setattr(timeouts, "_slots", slots)
    with pytest.raises(ParserBusy, match="retry shortly"):
        run_with_timeout(lambda: 1, 1)
    slots.release()
    assert run_with_timeout(lambda: "ok", 1) == "ok"
