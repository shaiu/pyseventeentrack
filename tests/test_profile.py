"""Define tests for the client object."""

# This module is a flat list of independent request/response scenarios, so it
# grows past pylint's 1000-line default as API surfaces are added.
# pylint: disable=too-many-lines

import logging
import re

import aiohttp
import pytest

from pyseventeentrack import Client
from pyseventeentrack.errors import (
    InvalidPackageDataError,
    InvalidTrackingNumberError,
    PackageNotFoundError,
    RequestError,
)
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 5
        assert packages[0].id == "internal-package-id"
        assert packages[0].location == "Paris"
        assert packages[0].first_carrier == 0
        assert packages[0].second_carrier == 0
        assert packages[1].location == "Spain"
        assert packages[2].location == "Milano Italy"
        assert packages[3].location == ""

@pytest.mark.asyncio
async def test_packages_timezones(aresponses):
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response_timezones.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 5
        assert packages[0].timestamp.isoformat() == "2019-02-26T15:05:34+00:00"
        assert packages[1].timestamp.isoformat() == "2019-02-26T15:05:34+00:00"
        assert packages[2].timestamp.isoformat() == "2019-02-26T15:05:34+00:00"
        assert packages[3].timestamp.isoformat() == "2019-02-26T15:05:34+00:00"
        assert packages[4].timestamp.isoformat() == "2019-02-26T15:05:34+00:00"

@pytest.mark.asyncio
async def test_packages_paginates(aresponses):
    """Test using the first reported total when a later page omits it."""
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
            text=load_fixture("packages_response_page_1.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 1.*"PerPage": 40.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_page_2.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 2.*"PerPage": 40.*'),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert [package.tracking_number for package in packages] == [
            "FIRST-PAGE-TRACKING",
            "SECOND-PAGE-TRACKING",
        ]
        assert packages[1].first_carrier == 123
        assert packages[1].second_carrier == 222
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_packages_continues_after_full_page_with_small_total_count(
    aresponses, monkeypatch
):
    """Test that a full page continues when TotalCount may mean page count."""
    monkeypatch.setattr("pyseventeentrack.profile.PACKAGES_PER_PAGE", 5)
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
        body_pattern=re.compile(r'.*"Page": 1.*"PerPage": 5.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_empty.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 2.*"PerPage": 5.*'),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 5
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_packages_continues_after_full_page_without_total_count(
    aresponses, monkeypatch, caplog
):
    """Test continuing after a full page when no total count is available."""
    monkeypatch.setattr("pyseventeentrack.profile.PACKAGES_PER_PAGE", 1)
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
            text=load_fixture("packages_response_missing_id.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 1.*"PerPage": 1.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_empty.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 2.*"PerPage": 1.*'),
    )

    with caplog.at_level(logging.DEBUG, logger="pyseventeentrack.profile"):
        async with aiohttp.ClientSession() as session:
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            packages = await client.profile.packages()

    assert [package.tracking_number for package in packages] == ["1234567890987654321"]
    assert "Continuing package pagination after full page 1 without TotalCount" in (
        caplog.text
    )
    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_packages_counts_received_rows(aresponses):
    """Test pagination without assuming every previous page was full."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    for page in range(1, 4):
        aresponses.add(
            "buyer.17track.net",
            "/orderapi/call",
            "post",
            aresponses.Response(
                text=load_fixture(f"packages_response_partial_page_{page}.json"),
                status=200,
            ),
            body_pattern=re.compile(rf'.*"Page": {page}.*"PerPage": 40.*'),
        )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert [package.tracking_number for package in packages] == [
            "PARTIAL-PAGE-1",
            "PARTIAL-PAGE-2A",
            "PARTIAL-PAGE-2B",
            "PARTIAL-PAGE-3",
        ]
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_packages_stops_on_empty_page(aresponses):
    """Test stopping pagination when the API returns an empty page."""
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
            text=load_fixture("packages_response_large_total.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 1.*"PerPage": 40.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_empty_page.json"), status=200
        ),
        body_pattern=re.compile(r'.*"Page": 2.*"PerPage": 40.*'),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert [package.tracking_number for package in packages] == [
            "FIRST-PAGE-TRACKING"
        ]
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_packages_stops_at_maximum_page(aresponses, monkeypatch):
    """Test bounding requests when distinct pages exceed the configured limit."""
    monkeypatch.setattr("pyseventeentrack.profile.MAX_PACKAGE_PAGES", 2)
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    for page, fixture in enumerate(
        ("packages_response_large_total.json", "packages_response_partial_page_2.json"),
        start=1,
    ):
        aresponses.add(
            "buyer.17track.net",
            "/orderapi/call",
            "post",
            aresponses.Response(text=load_fixture(fixture), status=200),
            body_pattern=re.compile(rf'.*"Page": {page}.*"PerPage": 40.*'),
        )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert [package.tracking_number for package in packages] == [
            "FIRST-PAGE-TRACKING",
            "PARTIAL-PAGE-2A",
            "PARTIAL-PAGE-2B",
        ]
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_packages_stops_on_repeated_page(aresponses):
    """Test stopping without appending packages when the API repeats a page."""
    aresponses.add(
        "user.17track.net",
        "/user-api/v1/sign-in-by-password",
        "post",
        aresponses.Response(
            text=load_fixture("authentication_success_response.json"), status=200
        ),
    )
    for page in range(1, 3):
        aresponses.add(
            "buyer.17track.net",
            "/orderapi/call",
            "post",
            aresponses.Response(
                text=load_fixture("packages_response_large_total.json"), status=200
            ),
            body_pattern=re.compile(rf'.*"Page": {page}.*"PerPage": 40.*'),
        )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert [package.tracking_number for package in packages] == [
            "FIRST-PAGE-TRACKING",
        ]
        aresponses.assert_plan_strictly_followed()


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_with_unknown_state.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 3
        assert packages[0].status == "Not Found"
        assert packages[1].status == "In Transit"
        assert packages[2].status == "Unknown"


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages()
        assert len(packages) == 5
        assert packages[0].timestamp.isoformat() == "2018-04-23T12:02:00+00:00"
        assert packages[1].timestamp.isoformat() == "2019-02-26T01:05:34+00:00"
        assert packages[2].timestamp.isoformat() == "1970-01-01T00:00:00+00:00"


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        packages = await client.profile.packages(tz="Asia/Jakarta")
        assert len(packages) == 5
        assert packages[0].timestamp.isoformat() == "2018-04-23T05:02:00+00:00"
        assert packages[1].timestamp.isoformat() == "2019-02-25T18:05:34+00:00"
        assert packages[2].timestamp.isoformat() == "1970-01-01T00:00:00+00:00"


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("summary_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        summary = await client.profile.summary()
        assert summary["Delivered"] == 0
        assert summary["Expired"] == 0
        assert summary["In Transit"] == 6
        assert summary["Not Found"] == 2
        assert summary["Ready to be Picked Up"] == 0
        assert summary["Alert"] == 0
        assert summary["Undelivered"] == 0
        assert summary["Unknown"] == 3


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
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
async def test_add_new_package_with_first_carrier(aresponses):
    """Test adding a new package with a first carrier."""
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("set_carrier_response.json"), status=200),
        body_pattern=re.compile(
            r'.*"method": "SetTrackCarrier".*"TrackInfoId": '
            r'"internal-package-id".*"FirstCarrier": 190625.*"SecondCarrier": 0.*'
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        await client.profile.add_package("1234567890987654321", first_carrier=190625)
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_add_new_package_sets_name_before_carrier(aresponses):
    """Test naming a package before assigning its carrier."""
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("set_friendly_name_response.json"), status=200
        ),
        body_pattern=re.compile(
            r'.*"method": "SetTrackRemark".*"TrackInfoId": '
            r'"internal-package-id".*"Remark": "Friendly name".*'
        ),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("set_carrier_failure_response.json"), status=200
        ),
        body_pattern=re.compile(
            r'.*"method": "SetTrackCarrier".*"TrackInfoId": '
            r'"internal-package-id".*"FirstCarrier": 190625.*"SecondCarrier": 0.*'
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        with pytest.raises(
            RequestError, match="Non-zero status code in response: -100"
        ):
            await client.profile.add_package(
                "1234567890987654321", "Friendly name", first_carrier=190625
            )
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_carrier", [None, 0])
async def test_add_new_package_with_second_carrier_without_first_carrier(
    first_carrier,
):
    """Test adding a new package with second carrier but no first carrier."""
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError):
            client = Client(session=session)
            await client.profile.add_package(
                "1234567890987654321",
                first_carrier=first_carrier,
                second_carrier=190625,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_name",
    ["packages_response_missing_id.json", "packages_response_empty_id.json"],
)
async def test_add_new_package_with_invalid_internal_id(aresponses, fixture_name):
    """Test adding a new package when its internal ID is missing or empty."""
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture(fixture_name), status=200),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(
            InvalidPackageDataError,
            match="Package ID is missing for tracking number: 1234567890987654321",
        ):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.add_package(
                "1234567890987654321", first_carrier=190625
            )


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
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
async def test_set_carrier_by_tracking_number(aresponses):
    """Test setting a carrier by tracking number."""
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
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("set_carrier_response.json"), status=200),
        body_pattern=re.compile(
            r'.*"method": "SetTrackCarrier".*"TrackInfoId": '
            r'"internal-package-id".*"FirstCarrier": 190625.*"SecondCarrier": 0.*'
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.set_carrier_by_tracking_number(
            "1234567890987654321", 190625
        )
        assert res is None
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_set_carrier_by_tracking_number_archived(aresponses):
    """Test setting a carrier for an archived package."""
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
            text=load_fixture("packages_response_empty.json"), status=200
        ),
        body_pattern=re.compile(r'.*"IsArchived": false.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_archived.json"), status=200
        ),
        body_pattern=re.compile(r'.*"IsArchived": true.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("set_carrier_response.json"), status=200),
        body_pattern=re.compile(
            r'.*"method": "SetTrackCarrier".*"TrackInfoId": '
            r'"archived-package-id".*"FirstCarrier": 190625.*"SecondCarrier": 222.*'
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        await client.profile.set_carrier_by_tracking_number("ARCHIVED-TRACKING", 190625)
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_set_carrier_by_tracking_number_non_existing(aresponses):
    """Test setting a carrier for a non-existing package."""
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
            text=load_fixture("packages_response_empty.json"), status=200
        ),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_empty.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidTrackingNumberError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.set_carrier_by_tracking_number("NOT-TRACKED", 190625)


@pytest.mark.asyncio
async def test_set_carrier_by_tracking_number_missing_internal_id(aresponses):
    """Test setting a carrier for a package with no internal ID."""
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
            text=load_fixture("packages_response_missing_id.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidPackageDataError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.set_carrier_by_tracking_number(
                "1234567890987654321", 190625
            )


@pytest.mark.asyncio
async def test_set_carrier_by_tracking_number_validates_carriers(aresponses):
    """Test validating carriers through the tracking-number wrapper."""
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

    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.set_carrier_by_tracking_number(
                "1234567890987654321", 0, 190625
            )


@pytest.mark.asyncio
async def test_set_carrier_by_tracking_number_preserved_second_blocks_clear(aresponses):
    """Test clearing the first carrier when the wrapper preserves the second.

    The wrapper resolves second_carrier before delegating, so it is the only
    caller that knows the value was preserved rather than passed in. Without its
    own validation the error would name an argument the caller never supplied.
    """
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
            text=load_fixture("packages_response_empty.json"), status=200
        ),
        body_pattern=re.compile(r'.*"IsArchived": false.*'),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_archived.json"), status=200
        ),
        body_pattern=re.compile(r'.*"IsArchived": true.*'),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        with pytest.raises(
            ValueError,
            match=r"cannot clear first_carrier while second_carrier \(222\) is set",
        ):
            await client.profile.set_carrier_by_tracking_number("ARCHIVED-TRACKING", 0)
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_set_carrier_preserves_existing_second_carrier(aresponses):
    """Test preserving the second carrier when setting by internal ID."""
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
            text=load_fixture("packages_response_archived.json"), status=200
        ),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("set_carrier_response.json"), status=200),
        body_pattern=re.compile(
            r'.*"method": "SetTrackCarrier".*"TrackInfoId": '
            r'"archived-package-id".*"FirstCarrier": 190625.*"SecondCarrier": 222.*'
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        await client.profile.set_carrier("archived-package-id", 190625)
        aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_set_carrier_rejects_empty_internal_id():
    """Test rejecting an empty internal package ID."""
    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        with pytest.raises(InvalidPackageDataError, match="Package ID cannot be empty"):
            await client.profile.set_carrier("", 190625, 0)


@pytest.mark.asyncio
async def test_set_carrier_rejects_invalid_carrier_combination():
    """Test validating carriers when setting by internal ID."""
    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        with pytest.raises(ValueError):
            await client.profile.set_carrier("internal-package-id", 0, 190625)


@pytest.mark.asyncio
async def test_set_carrier_rejects_clearing_first_with_preserved_second(aresponses):
    """Test the error when a preserved second carrier blocks clearing the first."""
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_archived.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        with pytest.raises(
            ValueError,
            match=r"cannot clear first_carrier while second_carrier \(222\) is set",
        ):
            await client.profile.set_carrier("archived-package-id", 0)


@pytest.mark.asyncio
async def test_set_carrier_internal_id_not_found(aresponses):
    """Test preserving a second carrier for an unknown internal ID."""
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_empty.json"), status=200
        ),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("packages_response_empty.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        with pytest.raises(
            PackageNotFoundError,
            match="Package not found by internal ID: unknown-id",
        ):
            await client.profile.set_carrier("unknown-id", 190625)


@pytest.mark.asyncio
async def test_set_carrier_by_tracking_number_error_response(aresponses):
    """Test setting a carrier when the API rejects the request."""
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
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("set_carrier_failure_response.json"), status=200
        ),
        body_pattern=re.compile(
            r'.*"method": "SetTrackCarrier".*"TrackInfoId": '
            r'"internal-package-id".*"FirstCarrier": 190625.*"SecondCarrier": 0.*'
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(
            RequestError, match="Non-zero status code in response: -100"
        ):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.set_carrier_by_tracking_number(
                "1234567890987654321", 190625
            )
        aresponses.assert_plan_strictly_followed()


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
    )
    aresponses.add(
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(
            text=load_fixture("archive_package_response.json"), status=200
        ),
        body_pattern=re.compile(
            r'.*"method": "SetTrackArchived".*"TrackInfoIds": '
            r'\["internal-package-id"\].*'
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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
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
async def test_archive_package_missing_internal_id(aresponses):
    """Test archiving a package with no internal ID."""
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
            text=load_fixture("packages_response_missing_id.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidPackageDataError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.archive_package("1234567890987654321")


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
        "buyer.17track.net",
        "/orderapi/call",
        "post",
        aresponses.Response(text=load_fixture("packages_response.json"), status=200),
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
