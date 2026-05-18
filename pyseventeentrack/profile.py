"""Define interaction with a user profile."""

import asyncio
from collections import Counter
from datetime import datetime
import logging
from typing import Callable, Coroutine, List, Optional, Union

from pytz import UnknownTimeZoneError, timezone

from .encrypt import rsa_encrypt
from .errors import (
    InvalidTrackingNumberError,
    NotLoggedInError,
    RequestError,
    SeventeenTrackError,
)
from .package import PACKAGE_STATUS_MAP, Package

_LOGGER: logging.Logger = logging.getLogger(__name__)

API_URL_BUYER: str = "https://buyer.17track.net/orderapi/call"
API_URL_TRACKLIST: str = "https://api.17track.net/track/v2.4/gettracklist"
API_URL_USER: str = "https://user.17track.net/user-api/v1/sign-in-by-password"
TRACKLIST_ORDER_BY_REGISTER_TIME_ASC: str = "11"
TRACKLIST_TIME_ZONE_OFFSET: int = 0
TRACKLIST_MAX_PAGES: int = 100
TRACKLIST_MAX_CONCURRENT_PAGES: int = 5

API_PACKAGE_STATUS_MAP = {
    "NotFound": 0,
    "InfoReceived": 10,
    "InTransit": 10,
    "Expired": 20,
    "PickUp": 30,
    "Undelivered": 35,
    "Delivered": 40,
    "Alert": 50,
}


def _package_int(package: dict, *keys: str) -> int:
    """Return an integer package value from the first matching key."""
    for key in keys:
        value = package.get(key)
        if value is None or isinstance(value, bool):
            continue

        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return 0


def _is_archived(package: dict) -> bool:
    """Return whether a package is archived according to the API response."""
    return bool(
        package.get("archive")
        or package.get("archived")
        or package.get("is_archive")
        or package.get("is_archived")
        or package.get("archived_at")
    )


def _package_string(package: dict, key: str) -> Optional[str]:
    """Return a string package value."""
    value = package.get(key)
    if value is not None:
        return str(value)

    return None


def _package_status(package: dict) -> int:
    """Return a pyseventeentrack package status code."""
    api_status = package.get("package_status")
    if not isinstance(api_status, str):
        return -1

    return API_PACKAGE_STATUS_MAP.get(api_status, -1)


def _parse_latest_event_time(value: Optional[str], tz: str) -> str:
    """Parse a tracklist timestamp into the format expected by Package."""
    if not value:
        return ""

    try:
        normalized_value = value.replace("Z", "+00:00") if value.endswith("Z") else value
        timestamp = datetime.fromisoformat(normalized_value)
    except ValueError:
        return value

    if timestamp.tzinfo is None:
        return timestamp.strftime("%Y-%m-%d %H:%M:%S")

    try:
        target_tz = timezone(tz)
    except UnknownTimeZoneError:
        target_tz = timezone("UTC")

    return timestamp.astimezone(target_tz).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_timezone(tz: str) -> str:
    """Return a timezone name safe to pass to Package."""
    try:
        timezone(tz)
    except UnknownTimeZoneError:
        return "UTC"

    return tz


def _has_next_page(data: dict, page_no: int) -> bool:
    """Return whether tracklist response metadata advertises another page."""
    for key in ("has_next_page", "has_more"):
        value = data.get(key)
        if isinstance(value, bool):
            return value

    next_page = data.get("next_page")
    if isinstance(next_page, int):
        return next_page > page_no

    for key in ("total_page", "total_pages", "page_count"):
        value = data.get(key)
        if isinstance(value, int):
            return page_no < value

    return False


def _page_count(data: dict) -> int:
    """Return the total page count advertised by tracklist metadata."""
    for key in ("total_page", "total_pages", "page_count"):
        value = data.get(key)
        if isinstance(value, bool):
            continue

        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue

    return 1


def _empty_summary() -> dict:
    """Return a zero-filled summary for known package statuses."""
    return {status: 0 for status in PACKAGE_STATUS_MAP.values()}


def _summary_status_name(status: object) -> Optional[str]:
    """Return a pyseventeentrack summary status name."""
    if isinstance(status, str):
        if status in API_PACKAGE_STATUS_MAP:
            return PACKAGE_STATUS_MAP[API_PACKAGE_STATUS_MAP[status]]

        if status in PACKAGE_STATUS_MAP.values():
            return status

        try:
            return PACKAGE_STATUS_MAP[int(status)]
        except (KeyError, ValueError):
            return "Unknown"

    if isinstance(status, int):
        return PACKAGE_STATUS_MAP.get(status, "Unknown")

    return None


def _summary_from_mapping(summary_data: dict) -> Optional[dict]:
    """Return a status summary from API-provided mapping data."""
    results = _empty_summary()
    unknown_count = 0
    found = False

    for status, count in summary_data.items():
        status_name = _summary_status_name(status)
        if not status_name:
            continue

        try:
            count_value = int(count)
        except (TypeError, ValueError):
            continue

        found = True
        if status_name == "Unknown":
            unknown_count += count_value
        else:
            results[status_name] += count_value

    if not found:
        return None

    if unknown_count:
        results["Unknown"] = unknown_count

    return results


def _summary_from_items(summary_data: list) -> Optional[dict]:
    """Return a status summary from API-provided list data."""
    results = _empty_summary()
    unknown_count = 0
    found = False

    for item in summary_data:
        if not isinstance(item, dict):
            continue

        status_name = None
        for status_key in ("package_status", "status", "state", "e"):
            status_name = _summary_status_name(item.get(status_key))
            if status_name:
                break

        if not status_name:
            continue

        count = None
        for count_key in ("count", "total", "ec"):
            count = item.get(count_key)
            if count is not None:
                break

        try:
            count_value = int(count)
        except (TypeError, ValueError):
            continue

        found = True
        if status_name == "Unknown":
            unknown_count += count_value
        else:
            results[status_name] += count_value

    if not found:
        return None

    if unknown_count:
        results["Unknown"] = unknown_count

    return results


def _summary_from_tracklist_data(data: dict) -> Optional[dict]:
    """Return a package summary when the API exposes aggregate counts."""
    for key in ("summary", "status_summary", "status_counts", "package_status_counts"):
        summary_data = data.get(key)
        if isinstance(summary_data, dict):
            return _summary_from_mapping(summary_data)

        if isinstance(summary_data, list):
            return _summary_from_items(summary_data)

    return None


def _packages_from_tracklist_data(data: dict) -> list:
    """Return package dictionaries from tracklist response data."""
    accepted = data.get("accepted")
    if not isinstance(accepted, list):
        return []

    return [package for package in accepted if isinstance(package, dict)]


class Profile:
    """Define a 17track.net profile manager."""

    def __init__(self, request: Callable[..., Coroutine]) -> None:
        """Initialize."""
        self._request: Callable[..., Coroutine] = request
        self.account_id: Optional[str] = None

    async def login(self, email: str, password: str) -> bool:
        """Login to the profile."""
        login_resp: dict = await self._request(
            "post",
            API_URL_USER,
            json={
                "source": 0,
                "account": email,
                "password": rsa_encrypt(password),
            },
        )

        _LOGGER.debug("Login response: %s", login_resp)

        account_data = login_resp.get("data")
        if not account_data or not account_data.get("gid"):
            _LOGGER.error(
                "Login response successful (code 0) but 'gid' is missing or empty in 'data': %s",
                login_resp,
            )
            return False
        self.account_id = account_data["gid"]
        return True

    async def packages(
        self,
        package_state: Union[int, str] = "",
        show_archived: bool = False,
        tz: str = "UTC",
    ) -> List[Package]:
        """Get the list of packages associated with the account."""
        package_tz = _normalize_timezone(tz)
        packages: List[Package] = []
        for package in await self._tracklist(show_archived=show_archived):
            tracking_number = _package_string(package, "number")
            if not tracking_number:
                continue

            status = _package_status(package)
            if package_state != "" and package_state not in (status, str(status)):
                continue

            friendly_name = _package_string(package, "tag") or _package_string(
                package, "remark"
            )
            kwargs: dict = {
                "id": package.get("id") or package.get("track_id"),
                "destination_country": _package_int(
                    package, "destination_country", "destination_country_id"
                ),
                "friendly_name": friendly_name,
                "info_text": _package_string(package, "latest_event_info"),
                "timestamp": _parse_latest_event_time(
                    _package_string(package, "latest_event_time"), package_tz
                ),
                "tz": package_tz,
                "origin_country": _package_int(
                    package, "origin_country", "origin_country_id"
                ),
                "package_type": _package_int(
                    package, "package_type", "track_state_type"
                ),
                "status": status,
            }
            packages.append(Package(tracking_number, **kwargs))
        return packages

    async def summary(self, show_archived: bool = False) -> dict:
        """Get a quick summary of how many packages are in an account."""
        tracklist_resp = await self._tracklist_page(1)
        data = (tracklist_resp or {}).get("data")
        if isinstance(data, dict):
            summary = _summary_from_tracklist_data(data)
            if summary is not None:
                return summary

        _LOGGER.debug("API did not provide summary; calculating from package list")
        summary = Counter(
            PACKAGE_STATUS_MAP.get(_package_status(package), "Unknown")
            for package in await self._tracklist(
                show_archived=show_archived, first_page_data=data
            )
        )

        return {
            **_empty_summary(),
            **{status: summary[status] for status in PACKAGE_STATUS_MAP.values()},
            **({"Unknown": summary["Unknown"]} if summary["Unknown"] else {}),
        }

    async def _tracklist(
        self, show_archived: bool = False, first_page_data: Optional[dict] = None
    ) -> list:
        """Get package data from the current 17TRACK track list API."""
        if first_page_data is None:
            tracklist_resp = await self._tracklist_page(1)
            data = (tracklist_resp or {}).get("data")
        else:
            data = first_page_data

        if not isinstance(data, dict):
            return []

        packages = _packages_from_tracklist_data(data)
        total_pages = min(_page_count(data), TRACKLIST_MAX_PAGES)
        if total_pages > 1:
            semaphore = asyncio.Semaphore(TRACKLIST_MAX_CONCURRENT_PAGES)

            async def fetch_page(page_no: int) -> dict:
                async with semaphore:
                    return await self._tracklist_page(page_no)

            pages = await asyncio.gather(
                *(fetch_page(page_no) for page_no in range(2, total_pages + 1))
            )
            for tracklist_resp in pages:
                page_data = (tracklist_resp or {}).get("data")
                if isinstance(page_data, dict):
                    packages.extend(_packages_from_tracklist_data(page_data))

        if total_pages == 1 and _has_next_page(data, 1):
            page_no = 1
            while page_no < TRACKLIST_MAX_PAGES:
                page_no += 1
                tracklist_resp = await self._tracklist_page(page_no)
                page_data = (tracklist_resp or {}).get("data")
                if not isinstance(page_data, dict):
                    break

                packages.extend(_packages_from_tracklist_data(page_data))

                if not _has_next_page(page_data, page_no):
                    break
        if show_archived:
            return packages

        return [package for package in packages if not _is_archived(package)]

    async def _tracklist_page(self, page_no: int) -> dict:
        """Get a package data page from the current 17TRACK track list API."""
        tracklist_resp: dict = await self._request(
            "post",
            API_URL_TRACKLIST,
            json={
                "page_no": page_no,
                "order_by": TRACKLIST_ORDER_BY_REGISTER_TIME_ASC,
                "timeZoneOffset": TRACKLIST_TIME_ZONE_OFFSET,
            },
        )

        _LOGGER.debug("Tracklist response: %s", tracklist_resp)

        code = (tracklist_resp or {}).get("code", 0)
        message = (tracklist_resp or {}).get("message")
        if code == -6:
            raise NotLoggedInError(
                f"Not logged in (Code: {code}, Message: {message})"
            )

        if code != 0:
            raise SeventeenTrackError(
                f"17TRACK API error (Code: {code}, Message: {message})"
            )

        return tracklist_resp

    async def add_package(
        self, tracking_number: str, friendly_name: Optional[str] = None
    ):
        """Add a package by tracking number to the tracking list."""
        add_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "AddTrackNo",
                "param": {"TrackNos": [tracking_number]},
            },
        )

        _LOGGER.debug("Add package response: %s", add_resp)

        code = add_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

        if not friendly_name:
            return

        packages = await self.packages()
        try:
            new_package = next(
                p for p in packages if p.tracking_number == tracking_number
            )
        except StopIteration as err:
            raise InvalidTrackingNumberError(
                f"Recently added package not found by tracking number: {tracking_number}"
            ) from err

        _LOGGER.debug("Found internal ID of recently added package: %s", new_package.id)

        await self.set_friendly_name(new_package.id, friendly_name)

    async def set_friendly_name(self, internal_id: str, friendly_name: str):
        """Set a friendly name to an already added tracking number.

        internal_id is not the tracking number, it's the ID of an existing package.
        """
        remark_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "SetTrackRemark",
                "param": {"TrackInfoId": internal_id, "Remark": friendly_name},
            },
        )

        _LOGGER.debug("Set friendly name response: %s", remark_resp)

        code = remark_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

    async def archive_package(self, tracking_number: str):
        """Archive a package by tracking number."""
        packages = await self.packages()

        try:
            package = next(p for p in packages if p.tracking_number == tracking_number)
        except StopIteration as err:
            raise InvalidTrackingNumberError(
                f"Package not found by tracking number: {tracking_number}"
            ) from err

        internal_id = package.id

        _LOGGER.debug("Found internal ID of package: %s", internal_id)

        archive_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "SetTrackArchived",
                "param": {"TrackInfoIds": [internal_id]},
            },
        )

        _LOGGER.debug("Archive package response: %s", archive_resp)

        code = archive_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")
