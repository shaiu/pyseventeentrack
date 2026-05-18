"""Define tests for the client object."""

import aiohttp
import pytest
from yarl import URL

import pyseventeentrack.profile as profile_module
from pyseventeentrack import Client
from pyseventeentrack.errors import (
    InvalidTrackingNumberError,
    NotLoggedInError,
    RequestError,
    SeventeenTrackError,
)
from pyseventeentrack.profile import API_URL_BUYER, API_URL_TRACKLIST, API_URL_USER
from .common import TEST_EMAIL, TEST_PASSWORD, load_fixture


@pytest.mark.asyncio
async def test_login_failure(aresponses):
    """Test that a failed login returns the correct response."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_failure_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        login_result = await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        assert login_result is False


@pytest.mark.asyncio
async def test_login_success(aresponses):
    """Test that a successful login returns the correct response."""
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
        login_result = await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        assert login_result is True


@pytest.mark.asyncio
async def test_no_explicit_session(aresponses):
    """Test not providing an explicit aiohttp ClientSession."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )

    client = Client()
    login_result = await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
    assert login_result is True


@pytest.mark.asyncio
async def test_no_explicit_session_keeps_login_cookies(aresponses):
    """Test temporary sessions share login cookies across requests."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            headers={"Set-Cookie": "sessionid=abc123; Path=/"},
            text=load_fixture("authentication_success_response.json"),
            status=200,
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    client = Client()
    assert await client.profile.login(TEST_EMAIL, TEST_PASSWORD) is True
    assert (
        client._cookie_jar.filter_cookies(URL(API_URL_TRACKLIST))["sessionid"].value  # pylint: disable=protected-access
        == "abc123"
    )
    packages = await client.profile.packages()
    assert len(packages) == 3


@pytest.mark.asyncio
async def test_packages(aresponses):
    """Test getting packages."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 3
        assert packages[0].friendly_name == "Office supplies"
        assert packages[0].info_text == "Arrived at destination facility"
        assert packages[0].tracking_number == "1234567890987654321"
        assert packages[1].status == "Unknown"
        assert packages[2].status == "Not Found"


@pytest.mark.asyncio
async def test_packages_with_unknown_state(aresponses):
    """Test getting packages."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(
            text=load_fixture("tracklist_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 3
        assert packages[0].status == "In Transit"
        assert packages[1].status == "Unknown"
        assert packages[2].status == "Not Found"


@pytest.mark.asyncio
async def test_packages_default_timezone(aresponses):
    """Test getting packages with default timezone."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 3
        assert packages[0].timestamp.isoformat() == "2026-05-18T07:30:00+00:00"
        assert packages[1].timestamp.isoformat() == "1970-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_packages_user_defined_timezone(aresponses):
    """Test getting packages with user-defined timezone."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages(tz="Asia/Jakarta")
        assert len(packages) == 3
        assert packages[0].timestamp.isoformat() == "2026-05-18T07:30:00+00:00"
        assert packages[1].timestamp.isoformat() == "1970-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_summary(aresponses):
    """Test getting package summary."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        summary = await client.profile.summary()
        assert summary["Delivered"] == 0
        assert summary["Expired"] == 0
        assert summary["In Transit"] == 1
        assert summary["Not Found"] == 1
        assert summary["Ready to be Picked Up"] == 0
        assert summary["Alert"] == 0
        assert summary["Undelivered"] == 0
        assert summary["Unknown"] == 1


@pytest.mark.asyncio
async def test_cookie_copy_to_api_domain_and_csrf_header():
    """Test copying login cookies to the API domain and CSRF header injection."""
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(quote_cookie=False)) as session:
        client = Client(session=session)
        session.cookie_jar.update_cookies(
            {"sessionid": "abc123", "csrf_token": "csrf123"}, URL(API_URL_USER)
        )

        client._copy_cookies_to_api_domains(session)  # pylint: disable=protected-access

        api_cookies = session.cookie_jar.filter_cookies(URL(API_URL_TRACKLIST))
        assert api_cookies["sessionid"].value == "abc123"
        assert api_cookies["csrf_token"].value == "csrf123"

        buyer_cookies = session.cookie_jar.filter_cookies(URL(API_URL_BUYER))
        assert buyer_cookies["sessionid"].value == "abc123"
        assert buyer_cookies["csrf_token"].value == "csrf123"

        headers = client._headers_for_url(  # pylint: disable=protected-access
            API_URL_TRACKLIST, session
        )
        assert headers["Accept"] == "*/*"
        assert headers["Origin"] == "https://admin.17track.net"
        assert headers["Referer"] == "https://admin.17track.net/"
        assert headers["x-csrf-token"] == "csrf123"


@pytest.mark.asyncio
async def test_packages_not_logged_in(aresponses):
    """Test that tracklist code -6 raises NotLoggedInError."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(
            text=load_fixture("tracklist_not_logged_in_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        with pytest.raises(NotLoggedInError):
            await client.profile.packages()


@pytest.mark.asyncio
async def test_packages_non_zero_error(aresponses):
    """Test that non-zero tracklist codes raise a general error."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_error_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        with pytest.raises(SeventeenTrackError):
            await client.profile.packages()


@pytest.mark.asyncio
async def test_packages_filters_package_state_zero(aresponses):
    """Test package_state filtering, including package_state=0."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages(package_state=0)
        assert len(packages) == 1
        assert packages[0].tracking_number == "NOTFOUNDSTATUS"
        assert packages[0].status == "Not Found"


@pytest.mark.asyncio
async def test_packages_show_archived(aresponses):
    """Test show_archived includes packages marked with archive."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages(show_archived=True)
        assert len(packages) == 4
        assert packages[1].tracking_number == "LP00432912409987"
        assert packages[1].friendly_name == "Book"
        assert packages[1].status == "Delivered"


@pytest.mark.asyncio
async def test_packages_parses_metadata(aresponses):
    """Test parsing package metadata when the new API exposes it."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages()
        assert packages[0].destination_country == "France"
        assert packages[0].origin_country == "China"
        assert packages[0].package_type == "Small Registered Package"


@pytest.mark.asyncio
async def test_packages_casts_string_and_int_values(aresponses):
    """Test package helpers cast API values into the expected types."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(
            text=load_fixture("tracklist_cast_values_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages()
        assert packages[0].tracking_number == "1234567890"
        assert packages[0].destination_country == "France"
        assert packages[0].origin_country == "China"
        assert packages[0].package_type == "Small Registered Package"


@pytest.mark.asyncio
async def test_packages_invalid_timezone_defaults_to_utc(aresponses):
    """Test invalid timezone names do not crash package parsing."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages(tz="Not/AZone")
        assert packages[0].timestamp.isoformat() == "2026-05-18T07:30:00+00:00"


@pytest.mark.asyncio
async def test_packages_fetches_paginated_results(aresponses):
    """Test tracklist pagination when the API advertises multiple pages."""
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(
            text=load_fixture("tracklist_page_1_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(
            text=load_fixture("tracklist_page_2_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages()
        assert [package.tracking_number for package in packages] == ["PAGE1", "PAGE2"]


@pytest.mark.asyncio
async def test_packages_pagination_safety_limit(aresponses, monkeypatch):
    """Test pagination stops at the configured safety limit."""
    monkeypatch.setattr(profile_module, "TRACKLIST_MAX_PAGES", 2)
    for _ in range(2):
        aresponses.add(
            "api.17track.net",
            "/track/v2.4/gettracklist",
            "post",
            aresponses.Response(
                text='{"code": 0, "message": "success", "data": {"has_more": true, "accepted": []}}',
                status=200,
            ),
        )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        packages = await client.profile.packages()
        assert packages == []


@pytest.mark.asyncio
async def test_add_new_package(aresponses):
    """Test adding a new package."""
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
        aresponses.Response(text=load_fixture("add_package_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        await client.profile.add_package("LP00432912409987")


@pytest.mark.asyncio
async def test_add_new_package_with_friendly_name(aresponses):
    """Test adding a new package with friendly name."""
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
        aresponses.Response(text=load_fixture("add_package_response.json"), status=200),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("set_friendly_name_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        await client.profile.add_package("1234567890987654321", "Friendly name")


@pytest.mark.asyncio
async def test_add_new_package_with_friendly_name_not_found(aresponses):
    """Test adding a new package with friendly name but package not found after adding it."""
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
        aresponses.Response(text=load_fixture("add_package_response.json"), status=200),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("set_friendly_name_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidTrackingNumberError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.add_package("1234567890987654321567", "Friendly name")


@pytest.mark.asyncio
async def test_add_new_package_with_friendly_name_error_response(aresponses):
    """Test adding a new package with friendly name but setting the name fails."""
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
        aresponses.Response(text=load_fixture("add_package_response.json"), status=200),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("set_friendly_name_failure_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.add_package("1234567890987654321", "Friendly name")


@pytest.mark.asyncio
async def test_add_existing_package(aresponses):
    """Test adding an existing new package."""
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
        aresponses.Response(
            text=load_fixture("add_package_existing_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.add_package("1234567890987654321")


@pytest.mark.asyncio
async def test_archive_package(aresponses):
    """Test archiving a package."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("archive_package_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.archive_package("1234567890987654321")
        assert res is None


@pytest.mark.asyncio
async def test_archive_package_non_existing(aresponses):
    """Test archiving a non existing package."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("archive_package_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidTrackingNumberError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.archive_package("1234567890987654321111")


@pytest.mark.asyncio
async def test_archive_package_error_response(aresponses):
    """Test archiving a package with failed response."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    aresponses.add(
        "api.17track.net",
        "/track/v2.4/gettracklist",
        "post",
        aresponses.Response(text=load_fixture("tracklist_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("archive_package_response_failure_response.json"),
            status=200,
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.archive_package("1234567890987654321")
