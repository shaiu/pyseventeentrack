"""Define interaction with a user profile."""

import json
import logging
from typing import Callable, Coroutine, List, Optional, Set, Tuple, Union
from datetime import datetime

from .encrypt import rsa_encrypt
from .errors import (
    InvalidPackageDataError,
    InvalidTrackingNumberError,
    NotLoggedInError,
    PackageNotFoundError,
    RequestError,
)
from .package import PACKAGE_STATUS_MAP, Package

_LOGGER: logging.Logger = logging.getLogger(__name__)

API_URL_BUYER: str = "https://buyer.17track.net/orderapi/call"
API_URL_USER: str = "https://user.17track.net/user-api/v1/sign-in-by-password"
PACKAGES_PER_PAGE: int = 40
MAX_PACKAGE_PAGES: int = 100


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
    ) -> list:
        """Get the list of packages associated with the account."""
        packages: List[Package] = []
        seen_page_signatures: Set[Tuple[Tuple[Optional[str], str], ...]] = set()
        total_count: Optional[int] = None
        page = 1
        while True:
            packages_resp: dict = await self._request(
                "post",
                API_URL_BUYER,
                json={
                    "version": "1.0",
                    "method": "GetTrackInfoList",
                    "param": {
                        "IsArchived": show_archived,
                        "Item": "",
                        "Page": page,
                        "PerPage": PACKAGES_PER_PAGE,
                        "PackageState": package_state,
                        "Sequence": "0",
                    },
                    "sourcetype": 0,
                },
            )

            _LOGGER.debug("Packages response: %s", packages_resp)

            code = (packages_resp or {}).get("Code", 0)
            if code != 0:
                raise NotLoggedInError(
                    f"Not logged in (Code: {code}, Message: "
                    f"{(packages_resp or {}).get('Message')})"
                )

            rows = (packages_resp or {}).get("Json") or []
            if not rows:
                break

            page_signature = tuple(
                (package.get("FTrackInfoId"), package["FTrackNo"]) for package in rows
            )
            if page_signature in seen_page_signatures:
                _LOGGER.warning(
                    "Stopping package pagination because page %s repeated package IDs",
                    page,
                )
                break
            seen_page_signatures.add(page_signature)

            for package in rows:
                event: dict = {}
                if package.get("FLastEvent"):
                    event = json.loads(package["FLastEvent"])

                timestamp = event.get("a")
                dd = event.get("dd")
                if dd:
                    try:
                        dt_str = f"{dd['d']}T{dd['t']}{dd.get('tz') or ''}"
                        timestamp = datetime.fromisoformat(dt_str)
                    except (KeyError, ValueError, TypeError):
                        pass
                        
                kwargs: dict = {
                    "id": package.get("FTrackInfoId"),
                    "destination_country": package.get("FSecondCountry", 0),
                    "friendly_name": package.get("FRemark"),
                    "info_text": event.get("z"),
                    "location": " ".join(
                        [event.get("c", ""), event.get("d", "")]
                    ).strip(),
                    "timestamp": timestamp,
                    "tz": tz,
                    "first_carrier": package.get("FFirstCarrier") or 0,
                    "origin_country": package.get("FFirstCountry", 0),
                    "package_type": package.get("FTrackStateType", 0),
                    "second_carrier": package.get("FSecondCarrier") or 0,
                    "status": package.get("FPackageState", 0),
                }
                packages.append(Package(package["FTrackNo"], **kwargs))

            if total_count is None:
                total_count = ((packages_resp or {}).get("pageInfo") or {}).get(
                    "TotalCount"
                ) or None
            if len(rows) < PACKAGES_PER_PAGE and (
                total_count is None or len(packages) >= total_count
            ):
                if total_count is None:
                    _LOGGER.debug(
                        "Stopping package pagination on page %s because TotalCount "
                        "is unavailable and the page returned %s of %s requested "
                        "packages",
                        page,
                        len(rows),
                        PACKAGES_PER_PAGE,
                    )
                break
            if page >= MAX_PACKAGE_PAGES:
                _LOGGER.warning(
                    "Stopping package pagination after %s pages",
                    MAX_PACKAGE_PAGES,
                )
                break
            if total_count is None:
                _LOGGER.debug(
                    "Continuing package pagination after full page %s without TotalCount",
                    page,
                )
            page += 1

        return packages

    async def _get_package_and_internal_id(
        self,
        tracking_number: str,
        not_found_message: Optional[str] = None,
        include_archived: bool = False,
    ) -> Tuple[Package, str]:
        """Find a package by tracking number and return its validated internal ID."""
        archived_states = (False, True) if include_archived else (False,)
        for show_archived in archived_states:
            packages = await self.packages(show_archived=show_archived)
            package = next(
                (p for p in packages if p.tracking_number == tracking_number), None
            )
            if package is None:
                continue
            if not package.id:
                raise InvalidPackageDataError(
                    f"Package ID is missing for tracking number: {tracking_number}"
                )

            _LOGGER.debug("Found internal ID of package: %s", package.id)
            return package, package.id

        raise InvalidTrackingNumberError(
            not_found_message
            or f"Package not found by tracking number: {tracking_number}"
        )

    async def _find_package_by_internal_id(self, internal_id: str) -> Package:
        """Find an active or archived package by its internal ID."""
        for show_archived in (False, True):
            packages = await self.packages(show_archived=show_archived)
            package = next((p for p in packages if p.id == internal_id), None)
            if package is not None:
                return package

        raise PackageNotFoundError(f"Package not found by internal ID: {internal_id}")

    @staticmethod
    def _validate_carriers(
        first_carrier: int,
        second_carrier: Optional[int],
        second_carrier_is_preserved: bool = False,
    ) -> None:
        """Validate the relationship between first and second carriers."""
        if not first_carrier and second_carrier:
            if second_carrier_is_preserved:
                raise ValueError(
                    "cannot clear first_carrier while "
                    f"second_carrier ({second_carrier}) is set"
                )
            raise ValueError("second_carrier cannot be set without first_carrier")

    async def summary(self, show_archived: bool = False) -> dict:
        """Get a quick summary of how many packages are in an account."""
        summary_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "GetIndexData",
                "param": {"IsArchived": show_archived},
                "sourcetype": 0,
            },
        )

        _LOGGER.debug("Summary response: %s", summary_resp)

        code = (summary_resp or {}).get("Code", 0)
        if code != 0:
            raise NotLoggedInError(
                f"Not logged in (Code: {code}, Message: {(summary_resp or {}).get('Message')})"
            )

        results: dict = {}
        for kind in ((summary_resp or {}).get("Json") or {}).get("eitem", []):
            key = PACKAGE_STATUS_MAP.get(kind["e"], "Unknown")
            value = kind["ec"]
            results[key] = value if key not in results else results[key] + value
        return results

    async def add_package(
        self,
        tracking_number: str,
        friendly_name: Optional[str] = None,
        first_carrier: Optional[int] = None,
        second_carrier: Optional[int] = None,
    ):
        """Add a package by tracking number to the tracking list."""
        if first_carrier is not None or second_carrier:
            self._validate_carriers(first_carrier or 0, second_carrier)

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

        if not friendly_name and first_carrier is None:
            return

        new_package, internal_id = await self._get_package_and_internal_id(
            tracking_number,
            f"Recently added package not found by tracking number: {tracking_number}",
        )

        if friendly_name:
            await self.set_friendly_name(internal_id, friendly_name)

        if first_carrier is not None:
            resolved_second_carrier = (
                new_package.second_carrier if second_carrier is None else second_carrier
            )
            self._validate_carriers(
                first_carrier,
                resolved_second_carrier,
                second_carrier_is_preserved=second_carrier is None,
            )
            await self.set_carrier(
                internal_id,
                first_carrier,
                resolved_second_carrier,
            )

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

    async def set_carrier_by_tracking_number(
        self,
        tracking_number: str,
        first_carrier: int,
        second_carrier: Optional[int] = None,
    ):
        """Set the carrier for an already added tracking number."""
        package, internal_id = await self._get_package_and_internal_id(
            tracking_number, include_archived=True
        )
        resolved_second_carrier = (
            package.second_carrier if second_carrier is None else second_carrier
        )
        self._validate_carriers(
            first_carrier,
            resolved_second_carrier,
            second_carrier_is_preserved=second_carrier is None,
        )
        await self.set_carrier(
            internal_id,
            first_carrier,
            resolved_second_carrier,
        )

    async def set_carrier(
        self,
        internal_id: str,
        first_carrier: int,
        second_carrier: Optional[int] = None,
    ):
        """Set the carrier for an already added tracking number.

        internal_id is not the tracking number, it's the ID of an existing package.
        Omitting second_carrier looks up the package to preserve its current value.
        Pass second_carrier explicitly to avoid that lookup.
        """
        if not internal_id:
            raise InvalidPackageDataError("Package ID cannot be empty")

        second_carrier_is_preserved = second_carrier is None
        if second_carrier is None:
            package = await self._find_package_by_internal_id(internal_id)
            second_carrier = package.second_carrier

        self._validate_carriers(
            first_carrier,
            second_carrier,
            second_carrier_is_preserved=second_carrier_is_preserved,
        )

        carrier_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "SetTrackCarrier",
                "param": {
                    "TrackInfoId": internal_id,
                    "FirstCarrier": first_carrier,
                    "SecondCarrier": second_carrier,
                },
            },
        )

        _LOGGER.debug("Set carrier response: %s", carrier_resp)

        code = carrier_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

    async def archive_package(self, tracking_number: str):
        """Archive a package by tracking number."""
        _, internal_id = await self._get_package_and_internal_id(tracking_number)

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
