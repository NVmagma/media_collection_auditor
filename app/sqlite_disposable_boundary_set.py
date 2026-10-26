"""Required-domain checks for disposable integration; never an ownership permit.

Callbacks are trusted fixture adapters. Sampling does not enforce continuity.
A failed instance stays blocked; recreating it is not production clearance.
"""
import math
import threading
from time import monotonic


def compose_disposable_boundaries(*, docker, nfs, host_storage, timer=monotonic):
    providers = (('docker', docker), ('nfs', nfs), ('host_storage', host_storage))
    if any(not callable(check) for _, check in providers) or not callable(timer):
        raise ValueError('All three callable disposable domain adapters required')
    lock = threading.Lock()
    failed = False

    def verify():
        nonlocal failed
        if not lock.acquire(blocking=False):
            failed = True
            raise RuntimeError('Concurrent or recursive disposable boundary check')
        try:
            if failed:
                raise RuntimeError('Disposable boundary failed; retained review required')
            def tick():
                value = timer()
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise RuntimeError('Disposable observation clock unavailable')
                return value
            started = previous = tick()
            # Revisit earlier domains after later observations. This is still
            # bounded sampling, not a replacement for actual exclusion controls.
            for name, check in providers + tuple(reversed(providers)):
                try:
                    if check() is not None:
                        raise ValueError('Adapter returned authority')
                except Exception:
                    raise RuntimeError('Disposable boundary unavailable: '+name) from None
                current = tick()
                if current < previous or current-started > 5:
                    raise RuntimeError('Disposable observation window expired')
                previous = current
                if failed:
                    raise RuntimeError('Disposable boundary interrupted; review required')
        except BaseException:
            failed = True
            raise
        finally:
            lock.release()
    return verify
