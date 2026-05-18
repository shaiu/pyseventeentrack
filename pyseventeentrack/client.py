"""Define a 17track.net client."""

import logging
from typing import Optional

from aiohttp import ClientSession, ClientTimeout, CookieJar
from aiohttp.client_exceptions import ClientError
from yarl import URL

from .errors import RequestError
from .profile import API_URL_BUYER, API_URL_TRACKLIST, API_URL_USER, Profile

_LOGGER: logging.Logger = logging.getLogger(__name__)

# from .track import Track

DEFAULT_TIMEOUT: int = 10
BROWSER_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Safari/537.36"
)


class Client:  # pylint: disable=too-few-public-methods
    """Define the client."""

    def __init__(self, *, session: Optional[ClientSession] = None) -> None:
        """Initialize."""
        self._session: Optional[ClientSession] = session
        self._cookie_jar: CookieJar = CookieJar(quote_cookie=False)

        self.profile: Profile = Profile(self._request)
        # This is disabled until a workaround can be found:
        # self.track = Track(self._request)

    def _copy_cookies_to_api_domains(self, session: ClientSession) -> None:
        """Copy login cookies to the authenticated API domains.

        The login endpoint (user.17track.net) may set cookies without a Domain
        attribute, which means they are only sent back to user.17track.net per
        RFC 6265. The track and buyer APIs need the same session cookies. This
        method copies them across.
        """
        login_url = URL(API_URL_USER)
        login_cookies = session.cookie_jar.filter_cookies(login_url)
        if login_cookies:
            cookie_values = {
                name: morsel.value for name, morsel in login_cookies.items()
            }
            for target_url in (URL(API_URL_TRACKLIST), URL(API_URL_BUYER)):
                session.cookie_jar.update_cookies(cookie_values, target_url)
                _LOGGER.debug(
                    "Copied %d cookie(s) from %s to %s",
                    len(cookie_values),
                    login_url.host,
                    target_url.host,
                )

    def _headers_for_url(self, url: str, session: ClientSession) -> dict:
        """Return browser-like headers expected by the 17TRACK web API."""
        request_url = URL(url)
        tracklist_url = URL(API_URL_TRACKLIST)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json;charset=UTF-8",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "User-Agent": BROWSER_USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }

        if request_url.host == URL(API_URL_USER).host:
            headers["Origin"] = "https://www.17track.net"
            headers["Referer"] = "https://www.17track.net/"
            headers["Sec-Fetch-Site"] = "same-site"

        if request_url.host == tracklist_url.host:
            headers["Accept"] = "*/*"
            headers["Content-Type"] = "application/json"
            headers["Origin"] = "https://admin.17track.net"
            headers["Referer"] = "https://admin.17track.net/"
            headers["Sec-Fetch-Site"] = "same-site"

            cookies = session.cookie_jar.filter_cookies(tracklist_url)
            csrf_token = cookies.get("csrf_token")
            if csrf_token:
                headers["x-csrf-token"] = csrf_token.value

        return headers

    async def _request(  # pylint: disable=too-many-arguments
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> dict:
        """Make a request against the RainMachine device."""
        use_running_session = self._session and not self._session.closed

        if use_running_session:
            session = self._session
        else:
            session = ClientSession(
                cookie_jar=self._cookie_jar,
                timeout=ClientTimeout(total=DEFAULT_TIMEOUT),
            )

        assert session

        try:
            request_headers = self._headers_for_url(url, session)
            if headers:
                request_headers.update(headers)

            async with session.request(
                method, url, headers=request_headers, params=params, json=json
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

                # After a successful login request, copy cookies to the API
                # domain so that subsequent API calls are authenticated.
                if url == API_URL_USER and session.cookie_jar:
                    self._copy_cookies_to_api_domains(session)

                return data
        except ClientError as err:
            raise RequestError(f"Error requesting data from {url}: {err}") from err
        finally:
            if not use_running_session:
                await session.close()
