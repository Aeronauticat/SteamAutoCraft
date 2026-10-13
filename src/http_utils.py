import time


def get_with_retry(
    session, url: str, params: dict, max_retries: int, interval: int,
    timeout: int = 15, headers: dict = None,
) -> dict:
    """GET with retry. Raises the last exception after max_retries attempts.
    429 is raised immediately without internal retry — caller handles backoff.
    """
    if max_retries <= 0:
        raise ValueError(f'max_retries must be >= 1, got {max_retries}')
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params, timeout=timeout, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            is_429 = hasattr(exc, 'response') and getattr(exc.response, 'status_code', None) == 429
            if is_429 or attempt >= max_retries - 1:
                raise exc
            time.sleep(interval)
    raise last_exc
