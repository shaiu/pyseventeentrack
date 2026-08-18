"""Define a 17track.net client."""

import logging
from typing import Optional

from aiohttp import ClientSession, ClientTimeout
from aiohttp.client_exceptions import ClientError
from yarl import URL

from .errors import RequestError
from .profile import API_URL_BUYER, API_URL_USER, Profile

_LOGGER: logging.Logger = logging.getLogger(__name__)

# from .track import Track

DEFAULT_TIMEOUT: int = 10


class Client:  # pylint: disable=too-few-public-methods
    """Define the client."""

    def __init__(self, *, session: Optional[ClientSession] = None) -> None:
        """Initialize."""
        # _session is the externally-supplied session; Client never closes it.
        self._session: Optional[ClientSession] = session
        # _internal_session is lazily created only when no external session was
        # supplied.  Client owns its lifecycle; close() releases it.
        self._internal_session: Optional[ClientSession] = None

        self.profile: Profile = Profile(self._request)
        # This is disabled until a workaround can be found:
        # self.track = Track(self._request)

    def _copy_cookies_to_buyer_domain(self, session: ClientSession) -> None:
        """Copy login cookies to the buyer API domain.

        The login endpoint (user.17track.net) may set cookies without a Domain
        attribute, which means they are only sent back to user.17track.net per
        RFC 6265. The buyer API lives on buyer.17track.net and needs the same
        session cookies. This method copies them across.
        """
        login_url = URL(API_URL_USER)
        buyer_url = URL(API_URL_BUYER)
        login_cookies = session.cookie_jar.filter_cookies(login_url)
        if login_cookies:
            session.cookie_jar.update_cookies(login_cookies, buyer_url)
            _LOGGER.debug(
                "Copied %d cookie(s) from %s to %s",
                len(login_cookies),
                login_url.host,
                buyer_url.host,
            )

    async def close(self) -> None:
        """Close the internally-managed session, if any.

        Has no effect when the caller supplied an external session (the caller
        owns its lifecycle) or when no request has been made yet.  Idempotent.
        """
        if self._internal_session and not self._internal_session.closed:
            await self._internal_session.close()
            self._internal_session = None

    async def _request(  # pylint: disable=too-many-arguments
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> dict:
        """Make a request against the 17track API."""
        # Determine which session to use and whether we own its lifecycle.
        #
        # Three cases:
        #   1. External session supplied and open  → reuse it; caller owns it,
        #      never close it.
        #   2. External session supplied but closed → create a throwaway session
        #      for this call only and close it in finally (pre-patch behaviour,
        #      preserves backwards compatibility).
        #   3. No external session                 → lazily create/reuse
        #      _internal_session; caller must call close() when done.
        temporary_session: bool = False

        if self._session is not None and not self._session.closed:
            # Case 1: open external session — reuse, never close.
            session: ClientSession = self._session
        elif self._session is not None and self._session.closed:
            # Case 2: closed external session — throwaway, close in finally.
            session = ClientSession(timeout=ClientTimeout(total=DEFAULT_TIMEOUT))
            temporary_session = True
        else:
            # Case 3: no external session — persistent internal session.
            if self._internal_session is None or self._internal_session.closed:
                self._internal_session = ClientSession(
                    timeout=ClientTimeout(total=DEFAULT_TIMEOUT)
                )
            session = self._internal_session

        try:
            async with session.request(
                method, url, headers=headers, params=params, json=json
            ) as resp:
                _LOGGER.debug(
                    "Response from %s: status=%s, content_type=%s",
                    url,
                    resp.status,
                    resp.content_type,
                )
                resp.raise_for_status()
                raw: str = await resp.text()
                _LOGGER.debug("Raw response body from %s: %r", url, raw)
                data: dict = await resp.json(content_type=None)
                if data is None:
                    _LOGGER.warning(
                        "Response from %s parsed as None; raw body was: %r", url, raw
                    )

                # After a successful login request, copy cookies to the buyer
                # domain so that subsequent API calls are authenticated.
                if url == API_URL_USER and session.cookie_jar:
                    self._copy_cookies_to_buyer_domain(session)

                return data
        except ClientError as err:
            raise RequestError(f"Error requesting data from {url}: {err}") from err
        finally:
            if temporary_session:
                await session.close()
