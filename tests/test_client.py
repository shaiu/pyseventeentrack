"""Define tests for the client object."""

import aiohttp
import pytest

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
async def test_external_session_closed_uses_temporary_session(aresponses):
    """Test that a closed external session falls back to a per-call throwaway.

    Pre-patch behaviour: when the caller-supplied session is already closed,
    _request creates a temporary ClientSession for that call only and closes it
    in finally.  This preserves backwards compatibility — callers that relied on
    the library working even with a closed session are not broken.

    Verification:
    - The request succeeds (temporary session is open and functional).
    - _internal_session is never set (the throwaway is not retained).
    - The external session remains closed throughout (we never reopen it).
    """
    aresponses.add(
        "random.domain",
        "/some/path",
        "get",
        aresponses.Response(text='{"Code": 0}', status=200),
    )

    session = aiohttp.ClientSession()
    await session.close()
    assert session.closed

    client = Client(session=session)
    result = await client._request("get", "https://random.domain/some/path")  # pylint: disable=protected-access

    # Request succeeded via the temporary session.
    assert result == {"Code": 0}

    # No internal session was created or retained.
    assert client._internal_session is None  # pylint: disable=protected-access

    # The external session is still closed (we never touched it).
    assert session.closed
