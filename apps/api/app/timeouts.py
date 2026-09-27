"""Hard wall-clock limits for CPU-bound work that cannot be interrupted cooperatively."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError


class OperationTimeout(Exception):
    pass


def run_with_timeout[T](fn: Callable[[], T], seconds: float) -> T:
    """Run ``fn`` on a fresh thread and give up after ``seconds``.

    Python cannot kill a thread, so on timeout the worker thread is abandoned:
    the executor is shut down without waiting and a new one serves the next
    call. The abandoned thread finishes (or leaks) on its own; the caller's
    state must not depend on it.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=seconds)
    except FutureTimeoutError as exc:
        raise OperationTimeout(f"Operation exceeded {seconds:g} seconds") from exc
    finally:
        executor.shutdown(wait=False)
