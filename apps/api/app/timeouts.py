"""Hard wall-clock limits for CPU-bound work that cannot be interrupted cooperatively."""

import threading
from collections.abc import Callable

from app.config import get_settings


class OperationTimeout(Exception):
    pass


class ParserBusy(Exception):
    pass


# Per-process cap on in-flight parses. Python cannot kill a thread, so a parse
# that outlives its timeout keeps running (and keeps its slot) until it finishes;
# a permanently hung parse holds a slot until the process restarts. The cap turns
# that leak into a bounded, visible "busy" condition instead of unbounded threads.
_slots = threading.BoundedSemaphore(get_settings().max_concurrent_parses)


def run_with_timeout[T](fn: Callable[[], T], seconds: float) -> T:
    """Run ``fn`` on a daemon thread and give up after ``seconds``.

    Raises ParserBusy when every slot is taken (callers retry later), and
    OperationTimeout when the work does not finish in time. The abandoned daemon
    thread never blocks interpreter shutdown; the caller's state must not depend
    on it.
    """
    slots = _slots
    if not slots.acquire(blocking=False):
        raise ParserBusy("Too many documents are being parsed right now; retry shortly")
    results: list[T] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            results.append(fn())
        except BaseException as exc:
            errors.append(exc)
        finally:
            # Release the semaphore this call acquired, even if the module-level
            # one was swapped (tests) while the thread was still running.
            slots.release()

    thread = threading.Thread(target=target, name="bounded-parse", daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise OperationTimeout(f"Operation exceeded {seconds:g} seconds")
    if errors:
        raise errors[0]
    return results[0]
