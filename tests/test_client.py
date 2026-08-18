"""Define tests for the client object."""

import aiohttp
import pytest

import pyseventeentrack.client as client_module
from pyseventeentrack import Client
from pyseventeentrack.errors import RequestError

from .common import TEST_EMAIL, TEST_PASSWORD, load_fixture


@pytest.mark.asyncio
async def test_bad_request(aresponses):
    """Test that a failed login returns the correct response."""
    aresponses.add(
        "random.domain", "/no/good", "get", aresponses.Response(text="", status=404)
    )

    with pytest.raises(RequestError):
        async with aiohttp.ClientSession() as session:
            client = Client(session=session)
            await client._request("get", "https://random.domain/no/good")  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_bare_client_login_then_packages(aresponses):
    """Test that a bare Client() reuses its session across login and packages().

    This is the core regression: with a throwaway session per call the cookie
    jar was discarded after login, so the packages() call would get Code -6
    (NotLoggedInError).  With a persistent internal session the cookies survive.

    The login mock sets a host-only cookie (no Domain attribute, per RFC 6265
    only replayed to user.17track.net).  The buyer mock is a callable that
    requires the cookie to be present — it returns Code -6 (NotLoggedInError)
    if the cookie is missing, and the packages fixture if it is present.  This
    means the test would fail under the old throwaway-session implementation
    because the cookie jar would be discarded between the two requests.
    """
    session_cookie = "session=test-auth-token"

    # Login response sets a host-only cookie (no Domain attribute).
    # aiohttp stores it keyed to user.17track.net; _copy_cookies_to_buyer_domain
    # then copies it to buyer.17track.net so the next request carries it.
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"),
            status=200,
            headers={"Set-Cookie": "session=test-auth-token; Path=/"},
        ),
    )

    # Buyer mock: callable so it can inspect the incoming Cookie header.
    # Returns NotLoggedInError (Code -6) when the cookie is absent — exactly
    # what the real API returns when the session jar was thrown away.
    def buyer_handler(request):
        cookie_header = request.headers.get("Cookie", "")
        if session_cookie not in cookie_header:
            return aresponses.Response(
                text='{"Code": -6, "Message": "Not logged in"}', status=200
            )
        return aresponses.Response(
            text=load_fixture("packages_response.json"), status=200
        )

    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        buyer_handler,
    )

    client = Client()
    try:
        login_result = await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        assert login_result is True

        packages = await client.profile.packages()
        assert len(packages) == 5
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_bare_client_internal_session_reused(aresponses):
    """Test that the internal session is created once and reused across calls."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )

    client = Client()
    assert client._internal_session is None  # pylint: disable=protected-access

    await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
    session_after_login = client._internal_session  # pylint: disable=protected-access
    assert session_after_login is not None

    await client.profile.packages()
    session_after_packages = client._internal_session  # pylint: disable=protected-access

    # Same object — not recreated between calls.
    assert session_after_packages is session_after_login

    await client.close()


@pytest.mark.asyncio
async def test_close_closes_internal_session(aresponses):
    """Test that close() closes the internally-managed session."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )

    client = Client()
    await client.profile.login(TEST_EMAIL, TEST_PASSWORD)

    internal = client._internal_session  # pylint: disable=protected-access
    assert internal is not None
    assert not internal.closed

    await client.close()

    assert internal.closed
    assert client._internal_session is None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_close_is_idempotent():
    """Test that calling close() multiple times does not raise."""
    client = Client()
    # No request made yet — close() should be a no-op.
    await client.close()
    await client.close()


@pytest.mark.asyncio
async def test_close_does_not_close_external_session(aresponses):
    """Test that close() leaves an externally supplied session open."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)

        # close() must not touch the caller-supplied session.
        await client.close()
        assert not session.closed


@pytest.mark.asyncio
async def test_external_session_closed_uses_temporary_session(aresponses, monkeypatch):
    """Test that a closed external session falls back to a per-call throwaway.

    This is an isolated per-call compatibility fallback: each call gets its own
    fresh ClientSession that is closed in finally.  Because each throwaway has an
    empty cookie jar, authenticated multi-request flows (login → packages) are NOT
    supported via this path — that is unchanged from pre-patch behaviour.

    Assertions:
    - The throwaway session is open during the request and closed afterwards.
    - _internal_session is never set (the throwaway is not retained on Client).
    - The external closed session is untouched throughout.
    - The throwaway is also closed when the request raises (HTTP error path).
    """
    created_sessions: list = []
    _real_ClientSession = aiohttp.ClientSession

    def session_factory(*args, **kwargs):
        s = _real_ClientSession(*args, **kwargs)
        created_sessions.append(s)
        return s

    monkeypatch.setattr(client_module, "ClientSession", session_factory)

    # --- successful request path ---
    aresponses.add(
        "random.domain",
        "/some/path",
        "get",
        aresponses.Response(text='{"Code": 0}', status=200),
    )

    closed_session = _real_ClientSession()
    await closed_session.close()
    assert closed_session.closed

    client = Client(session=closed_session)
    result = await client._request("get", "https://random.domain/some/path")  # pylint: disable=protected-access

    assert result == {"Code": 0}
    assert len(created_sessions) == 1
    throwaway_ok = created_sessions[0]
    # Throwaway must be closed after the call completes.
    assert throwaway_ok.closed
    # Client must not retain it as _internal_session.
    assert client._internal_session is None  # pylint: disable=protected-access
    # External session untouched.
    assert closed_session.closed

    # --- HTTP error path: throwaway must also be closed on exception ---
    aresponses.add(
        "random.domain",
        "/some/path",
        "get",
        aresponses.Response(text="", status=500),
    )

    with pytest.raises(RequestError):
        await client._request("get", "https://random.domain/some/path")  # pylint: disable=protected-access

    assert len(created_sessions) == 2
    throwaway_err = created_sessions[1]
    # Throwaway from the error path must also be closed.
    assert throwaway_err.closed
    # Still no internal session retained.
    assert client._internal_session is None  # pylint: disable=protected-access
