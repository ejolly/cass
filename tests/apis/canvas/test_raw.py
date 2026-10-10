"""Tests for cass.apis.canvas.raw — raw API path and form helpers."""

import httpx
import pytest

from cass.apis.canvas.raw import (
    api_path,
    form_content,
    parse_body,
    parse_form,
    request_fields,
)


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


def test_parse_form_nests_brackets():
    pairs = [("quiz[title]", "Q"), ("quiz[published]", "false")]
    assert parse_form(pairs) == {"quiz": {"title": "Q", "published": "false"}}


def test_parse_form_lists():
    pairs = [("a[types][]", "x"), ("a[types][]", "y")]
    assert parse_form(pairs) == {"a": {"types": ["x", "y"]}}


def test_parse_form_list_of_dicts():
    pairs = [("order[][id]", "1"), ("order[][id]", "2")]
    assert parse_form(pairs) == {"order": [{"id": "1"}, {"id": "2"}]}


def test_parse_form_plain_and_malformed_keys():
    pairs = [("hidden", "true"), ("a[b", "1")]
    assert parse_form(pairs) == {"hidden": "true", "a[b": "1"}


def test_request_fields_unwraps_single_wrapper():
    assert request_fields({"quiz": {"title": "Q"}}) == {"title": "Q"}
    assert request_fields({"title": "A", "message": "B"}) == {
        "title": "A",
        "message": "B",
    }
    assert request_fields({"hidden": "true"}) == {"hidden": "true"}


def test_parse_body_json_and_form():
    url = "https://canvas.example.com/api/v1/courses/1/quizzes"
    as_json = httpx.Request("POST", url, json={"question": {"a": 1}})
    assert parse_body(as_json) == {"question": {"a": 1}}
    as_form = httpx.Request("PUT", url, data={"hidden": True})
    assert parse_body(as_form) == {"hidden": "true"}
    assert parse_body(httpx.Request("DELETE", url)) == {}
