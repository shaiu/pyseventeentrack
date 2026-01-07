"""Define tests for the client object."""

import aiohttp
import pytest

from pyseventeentrack import Client
from pyseventeentrack.errors import InvalidTrackingNumberError, RequestError
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
        assert packages[0].location == "Paris"
        assert packages[1].location == "Spain"
        assert packages[2].location == "Milano Italy"
        assert packages[3].location == ""


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


@pytest.mark.asyncio
async def test_activate_package(aresponses):
    """Test activating a package."""
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
            text=load_fixture("activate_package_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.activate_package("1234567890987654321")
        assert res is None


@pytest.mark.asyncio
async def test_activate_package_non_existing(aresponses):
    """Test activating a non existing package."""
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
            text=load_fixture("activate_package_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidTrackingNumberError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.activate_package("1234567890987654321111")


@pytest.mark.asyncio
async def test_activate_package_error_response(aresponses):
    """Test activating a package with failed response."""
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
            text=load_fixture("activate_package_response_failure_response.json"),
            status=200,
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.activate_package("1234567890987654321")


@pytest.mark.asyncio
async def test_delete_package(aresponses):
    """Test deleting a package."""
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
        aresponses.Response(text=load_fixture("delete_package_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.delete_package("1234567890987654321")
        assert res is None


@pytest.mark.asyncio
async def test_delete_package_non_existing(aresponses):
    """Test deleting a non existing package."""
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
        aresponses.Response(text=load_fixture("delete_package_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(InvalidTrackingNumberError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.delete_package("1234567890987654321111")


@pytest.mark.asyncio
async def test_delete_package_error_response(aresponses):
    """Test deleting a package with failed response."""
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
            text=load_fixture("delete_package_response_failure_response.json"),
            status=200,
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.delete_package("1234567890987654321")


@pytest.mark.asyncio
async def test_set_tag_type(aresponses):
    """Test setting tag type."""
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
        aresponses.Response(text=load_fixture("set_tag_type_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.set_tag_type("1234567890987654321", "0")
        assert res is None


@pytest.mark.asyncio
async def test_set_tag_type_error_response(aresponses):
    """Test setting tag type with failed response."""
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
            text=load_fixture("set_tag_type_response_failure_response.json"),
            status=200,
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.set_tag_type("1234567890987654321", "0")


@pytest.mark.asyncio
async def test_set_carrier(aresponses):
    """Test setting carrier."""
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
        aresponses.Response(text=load_fixture("set_carrier_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.set_carrier("1234567890987654321", "100001", "0")
        assert res is None


@pytest.mark.asyncio
async def test_set_carrier_error_response(aresponses):
    """Test setting carrier with failed response."""
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
            text=load_fixture("set_carrier_response_failure_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.set_carrier("1234567890987654321", "100001", "0")


@pytest.mark.asyncio
async def test_track_info_by_id(aresponses):
    """Test getting track info by internal ID."""
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
            text=load_fixture("track_info_by_id_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        items = await client.profile.track_info_by_id("1234567890987654321")
        assert len(items) == 1
        assert items[0]["FTrackInfoId"] == "1234567890987654321"


@pytest.mark.asyncio
async def test_track_info_by_id_empty():
    """Test getting track info with no IDs."""
    client = Client()
    items = await client.profile.track_info_by_id()
    assert items == []


@pytest.mark.asyncio
async def test_track_info_by_id_error_response(aresponses):
    """Test getting track info with failed response."""
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
            text=load_fixture("track_info_by_id_failure_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.track_info_by_id("1234567890987654321")


@pytest.mark.asyncio
async def test_order_info_by_id(aresponses):
    """Test getting order info by internal ID."""
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
            text=load_fixture("order_info_by_id_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        order = await client.profile.order_info_by_id("1234567890987654321")
        assert order["opn"] == "Acme"
        assert order["ptoid"] == "123"
        assert order["pt"] == "01"
        assert order["otime"] == "2024-12-01"


@pytest.mark.asyncio
async def test_order_info_by_id_error_response(aresponses):
    """Test getting order info with failed response."""
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
            text=load_fixture("order_info_by_id_failure_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.order_info_by_id("1234567890987654321")


@pytest.mark.asyncio
async def test_save_order_info(aresponses):
    """Test saving order info."""
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
        aresponses.Response(text=load_fixture("save_order_info_response.json"), status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = Client(session=session)
        await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
        res = await client.profile.save_order_info(
            "1234567890987654321",
            opn="Acme",
            ptoid="123",
            pt="01",
            otime="2024-12-01",
        )
        assert res is None


@pytest.mark.asyncio
async def test_save_order_info_error_response(aresponses):
    """Test saving order info with failed response."""
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
            text=load_fixture("save_order_info_failure_response.json"), status=200
        ),
    )

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RequestError):
            client = Client(session=session)
            await client.profile.login(TEST_EMAIL, TEST_PASSWORD)
            await client.profile.save_order_info("1234567890987654321", opn="Acme")
