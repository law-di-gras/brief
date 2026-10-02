"""Read-only Clio Manage client.

ClioReadOnly has a get() method and nothing else. There is no code path in Brief
that writes to Clio. (Token refresh in auth.py talks to Clio's OAuth server, not
to the Manage API.)
"""
import logging
import os
import time

import httpx

log = logging.getLogger(__name__)

API_PREFIX = "/api/v4"


def clio_base() -> str:
    return os.environ.get("CLIO_BASE", "https://app.clio.com").rstrip("/")


class ClioReadOnly:
    def __init__(self, token_provider):
        """token_provider() returns a current access token; token_provider(force=True) refreshes it."""
        self._token = token_provider
        self._http = httpx.Client(base_url=clio_base(), timeout=60, follow_redirects=True)

    def get(self, path: str, params: dict | None = None, raw: bool = False):
        """GET a Clio path.

        JSON list endpoints are followed through every page (meta.paging.next) and
        returned as {"data": [...all records...]}. With raw=True the response bytes
        are returned (document downloads).
        """
        url = path if path.startswith("http") else API_PREFIX + path
        params = dict(params or {})
        if not raw and "limit" not in params and path.endswith("s.json"):
            params["limit"] = 200
        records, single = [], None
        while url:
            resp = self._request(url, params)
            if raw:
                return resp.content
            body = resp.json()
            data = body.get("data")
            if isinstance(data, list):
                records.extend(data)
            else:
                single = body
            nxt = (body.get("meta") or {}).get("paging", {}).get("next")
            url, params = (nxt, None) if nxt else (None, None)
        return single if single is not None else {"data": records}

    def _request(self, url, params):
        refreshed = False
        for attempt in range(6):
            resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {self._token()}"})
            if resp.status_code == 401 and not refreshed:
                self._token(force=True)
                refreshed = True
                continue
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                log.info("Clio rate limit, sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp


def make_client(user_id=None):
    """The Clio client: live Clio as `user_id` (default: the acting user, else the service account),
    or the seed fixture when CLIO_SOURCE=fixture."""
    if os.environ.get("CLIO_SOURCE") == "fixture":
        from backend.pipeline.fixture_clio import FixtureClio
        return FixtureClio()
    from backend.pipeline import auth
    return ClioReadOnly(lambda force=False: auth.access_token(user_id, force=force))
