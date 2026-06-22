"""Define interaction with a user profile."""

import json
import logging
from typing import Callable, Coroutine, List, Optional, Union

from .encrypt import rsa_encrypt
from .errors import InvalidTrackingNumberError, NotLoggedInError, RequestError
from .package import PACKAGE_STATUS_MAP, Package

_LOGGER: logging.Logger = logging.getLogger(__name__)

API_URL_BUYER: str = "https://buyer.17track.net/orderapi/call"
API_URL_USER: str = "https://user.17track.net/user-api/v1/sign-in-by-password"


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
        packages_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "GetTrackInfoList",
                "param": {
                    "IsArchived": show_archived,
                    "Item": "",
                    "Page": 1,
                    "PerPage": 40,
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
                f"Not logged in (Code: {code}, Message: {(packages_resp or {}).get('Message')})"
            )

        packages: List[Package] = []
        for package in (packages_resp or {}).get("Json") or []:
            event: dict = {}
            last_event_raw: str = package.get("FLastEvent")
            if last_event_raw:
                event = json.loads(last_event_raw)

            kwargs: dict = {
                "id": package.get("FTrackInfoId"),
                "destination_country": package.get("FSecondCountry", 0),
                "friendly_name": package.get("FRemark"),
                "info_text": event.get("z"),
                "location": " ".join([event.get("c", ""), event.get("d", "")]).strip(),
                "timestamp": event.get("a"),
                "tz": tz,
                "first_carrier": package.get("FFirstCarrier", 0),
                "first_carrier_options": package.get("FFirstCarrierOptions"),
                "origin_country": package.get("FFirstCountry", 0),
                "package_type": package.get("FTrackStateType", 0),
                "second_carrier": package.get("FSecondCarrier", 0),
                "status": package.get("FPackageState", 0),
            }
            packages.append(Package(package["FTrackNo"], **kwargs))
        return packages

    async def _find_package_by_tracking_number(
        self, tracking_number: str, not_found_message: Optional[str] = None
    ) -> Package:
        """Find a package by tracking number."""
        packages = await self.packages()
        try:
            return next(p for p in packages if p.tracking_number == tracking_number)
        except StopIteration as err:
            raise InvalidTrackingNumberError(
                not_found_message
                or f"Package not found by tracking number: {tracking_number}"
            ) from err

    @staticmethod
    def _get_package_internal_id(package: Package, tracking_number: str) -> str:
        """Get the internal package ID for a package."""
        if package.id is None:
            raise RequestError(
                f"Package ID is missing for tracking number: {tracking_number}"
            )

        return package.id

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
        second_carrier: int = 0,
    ):
        """Add a package by tracking number to the tracking list."""
        if first_carrier is None and second_carrier != 0:
            raise ValueError("second_carrier cannot be set without first_carrier")

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

        new_package = await self._find_package_by_tracking_number(
            tracking_number,
            f"Recently added package not found by tracking number: {tracking_number}",
        )
        internal_id = self._get_package_internal_id(new_package, tracking_number)

        _LOGGER.debug("Found internal ID of recently added package: %s", internal_id)

        if first_carrier is not None:
            await self.set_carrier(internal_id, first_carrier, second_carrier)

        if friendly_name:
            await self.set_friendly_name(internal_id, friendly_name)

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

    async def change_carrier(
        self, tracking_number: str, first_carrier: int, second_carrier: int = 0
    ):
        """Set the carrier for an already added tracking number."""
        package = await self._find_package_by_tracking_number(tracking_number)
        internal_id = self._get_package_internal_id(package, tracking_number)

        _LOGGER.debug("Found internal ID of package: %s", internal_id)

        await self.set_carrier(internal_id, first_carrier, second_carrier)

    async def set_carrier(
        self, internal_id: str, first_carrier: int, second_carrier: int = 0
    ):
        """Set the carrier for an already added tracking number.

        internal_id is not the tracking number, it's the ID of an existing package.
        """
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
        package = await self._find_package_by_tracking_number(tracking_number)
        internal_id = self._get_package_internal_id(package, tracking_number)

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
