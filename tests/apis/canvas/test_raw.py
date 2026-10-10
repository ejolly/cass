"""Tests for cass.apis.canvas.raw — raw API path and form helpers."""

import pytest

from cass.apis.canvas.raw import api_path, form_content


@pytest.mark.parametrize("given", ["/api/v1/courses/1", "/courses/1", "courses/1"])
def test_api_path_normalizes(given):
    assert api_path(given) == "/courses/1"


def test_api_path_keeps_absolute_url():
    url = "https://canvas.example.com/api/v1/courses/1?page=2"
    assert api_path(url) == url


def test_form_content_keeps_repeated_keys():
    body = form_content([("order[][id]", 1), ("order[][id]", 2)])
    assert body == b"order%5B%5D%5Bid%5D=1&order%5B%5D%5Bid%5D=2"


def test_form_content_encodes_like_httpx():
    # httpx sends True/False as true/false and None as an empty value
    assert (
        form_content([("a", True), ("b", False), ("c", None)]) == b"a=true&b=false&c="
    )
