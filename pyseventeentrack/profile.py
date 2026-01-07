"""Define interaction with a user profile."""

import json
import logging
from typing import Callable, Coroutine, List, Optional, Union

from .encrypt import rsa_encrypt
from .errors import InvalidTrackingNumberError, RequestError
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

        packages: List[Package] = []
        for package in packages_resp.get("Json", []):
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
                "origin_country": package.get("FFirstCountry", 0),
                "package_type": package.get("FTrackStateType", 0),
                "status": package.get("FPackageState", 0),
            }
            packages.append(Package(package["FTrackNo"], **kwargs))
        return packages

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

        results: dict = {}
        for kind in summary_resp.get("Json", {}).get("eitem", []):
            key = PACKAGE_STATUS_MAP.get(kind["e"], "Unknown")
            value = kind["ec"]
            results[key] = value if key not in results else results[key] + value
        return results

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

    async def activate_package(self, tracking_number: str):
        """Activate (unarchive) a package by tracking number."""
        packages = await self.packages()

        try:
            package = next(p for p in packages if p.tracking_number == tracking_number)
        except StopIteration as err:
            raise InvalidTrackingNumberError(
                f"Package not found by tracking number: {tracking_number}"
            ) from err

        internal_id = package.id

        _LOGGER.debug("Found internal ID of package: %s", internal_id)

        activate_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "SetTrackActivate",
                "param": {"TrackInfoIds": [internal_id]},
            },
        )

        _LOGGER.debug("Activate package response: %s", activate_resp)

        code = activate_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

    async def delete_package(self, tracking_number: str):
        """Delete a package by tracking number."""
        packages = await self.packages()

        try:
            package = next(p for p in packages if p.tracking_number == tracking_number)
        except StopIteration as err:
            raise InvalidTrackingNumberError(
                f"Package not found by tracking number: {tracking_number}"
            ) from err

        internal_id = package.id

        _LOGGER.debug("Found internal ID of package: %s", internal_id)

        delete_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "DelTrackNo",
                "param": {"TrackInfoIds": [internal_id]},
            },
        )

        _LOGGER.debug("Delete package response: %s", delete_resp)

        code = delete_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

    async def set_tag_type(self, internal_id: str, tag: str):
        """Set the tag type for an existing package."""
        tag_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "SetTrackTagType",
                "param": {"tid": internal_id, "tag": tag},
            },
        )

        _LOGGER.debug("Set tag type response: %s", tag_resp)

        code = tag_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

    async def set_carrier(
        self, internal_id: str, first_carrier: str, second_carrier: str = "0"
    ):
        """Set the carrier(s) for an existing package."""
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

    async def track_info_by_id(self, *track_info_ids: str, isa: bool = False) -> list:
        """Get tracking info by internal tracking IDs."""
        if not track_info_ids:
            return []

        track_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "GetTrackInfoById",
                "param": {"isa": isa, "tids": list(track_info_ids)},
            },
        )

        _LOGGER.debug("Track info by ID response: %s", track_resp)

        code = track_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

        return track_resp.get("Json", [])

    async def order_info_by_id(self, internal_id: str) -> dict:
        """Get order info by internal tracking ID."""
        order_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "GetOrderInfoById",
                "param": {"tid": internal_id},
            },
        )

        _LOGGER.debug("Order info response: %s", order_resp)

        code = order_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")

        return order_resp.get("Json", {}).get("order", {})

    async def save_order_info(
        self,
        internal_id: str,
        *,
        opn: Optional[str] = None,
        ptoid: Optional[str] = None,
        pt: Optional[str] = None,
        otime: Optional[str] = None,
    ):
        """Save order info for an existing package."""
        param: dict = {"tid": internal_id}
        if opn is not None:
            param["opn"] = opn
        if ptoid is not None:
            param["ptoid"] = ptoid
        if pt is not None:
            param["pt"] = pt
        if otime is not None:
            param["otime"] = otime

        order_resp: dict = await self._request(
            "post",
            API_URL_BUYER,
            json={
                "version": "1.0",
                "method": "SaveOrderInfo",
                "param": param,
            },
        )

        _LOGGER.debug("Save order info response: %s", order_resp)

        code = order_resp.get("Code")
        if code != 0:
            raise RequestError(f"Non-zero status code in response: {code}")
