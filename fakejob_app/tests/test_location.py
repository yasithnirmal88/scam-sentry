"""Tests for location.py: best-effort country/region normalization."""

from location import (
    REMOTE, canonical_country, canonical_region, normalize_location,
    region_for_country,
)


def test_city_and_country():
    assert normalize_location("Berlin, Germany") == ("Germany", "Europe")
    assert normalize_location("Colombo, Sri Lanka") == ("Sri Lanka", "Asia")
    assert normalize_location("Berlin, GERMANY") == ("Germany", "Europe")


def test_country_only():
    assert normalize_location("Germany") == ("Germany", "Europe")
    assert normalize_location("Sri Lanka") == ("Sri Lanka", "Asia")
    assert normalize_location("Singapore") == ("Singapore", "Asia")


def test_multi_segment_with_state():
    assert normalize_location("Austin, TX, USA") == ("United States", "North America")


def test_abbreviations():
    assert normalize_location("USA") == ("United States", "North America")
    assert normalize_location("U.S.A.") == ("United States", "North America")
    assert normalize_location("London, UK") == ("United Kingdom", "Europe")
    assert normalize_location("Dublin, IE") == ("Ireland", "Europe")
    assert normalize_location("EU") == ("Europe", "Europe")


def test_remote_and_worldwide():
    for text in ("Remote", "remote", "Worldwide", "Anywhere",
                 "Work from anywhere", "Remote - Worldwide", "Global"):
        assert normalize_location(text) == (REMOTE, REMOTE), text


def test_remote_with_country_still_remote():
    assert normalize_location("Remote, US") == (REMOTE, REMOTE)
    assert normalize_location("Berlin, Germany (Remote)") == (REMOTE, REMOTE)


def test_country_inside_a_longer_string():
    assert normalize_location("Berlin area, Germany") == ("Germany", "Europe")
    assert normalize_location("based in Canada") == ("Canada", "North America")


def test_unknown_returns_blanks():
    assert normalize_location("New York, NY") == ("", "")
    assert normalize_location("Somewhere") == ("", "")
    assert normalize_location("") == ("", "")
    assert normalize_location(None) == ("", "")
    assert normalize_location("   ") == ("", "")


def test_never_raises_on_garbage():
    for garbage in ("!@#$%^&*()", 123, [], {"x": 1}, "   ,, ,"):
        country, region = normalize_location(garbage)
        assert isinstance(country, str) and isinstance(region, str)


def test_canonical_country():
    assert canonical_country("usa") == "United States"
    assert canonical_country("UK") == "United Kingdom"
    assert canonical_country("Germany") == "Germany"
    assert canonical_country("Remote") == REMOTE
    assert canonical_country("Nowhereland") == ""
    assert canonical_country("") == ""


def test_canonical_region():
    assert canonical_region("europe") == "Europe"
    assert canonical_region("EU") == "Europe"
    assert canonical_region("asia") == "Asia"
    assert canonical_region("middle east") == "Middle East"
    assert canonical_region("does-not-exist") == ""


def test_region_for_country():
    assert region_for_country("Germany") == "Europe"
    assert region_for_country("United States") == "North America"
    assert region_for_country("Nope") is None
