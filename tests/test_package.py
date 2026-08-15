"""Define tests for package objects."""

from pyseventeentrack.package import Package


def test_existing_positional_constructor_order():
    """Test that carrier fields do not shift existing positional arguments."""
    package = Package(
        "TRACKING-NUMBER",
        0,
        None,
        None,
        None,
        "",
        None,
        0,
        0,
        0,
        "English",
        "UTC",
    )

    assert package.tracking_info_language == "English"
    assert package.tz == "UTC"
    assert package.first_carrier == 0
    assert package.second_carrier == 0
