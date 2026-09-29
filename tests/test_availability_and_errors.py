"""Seat availability as an option, and server errors inside the batch reply.

Every request here goes through a real MatrixClient to an httpx.MockTransport
that answers in Matrix's multipart batch format, so the body on the wire and
the cache key built from it are the ones a live search would use.
"""

from __future__ import annotations

import json

import httpx
import pytest

from itamx.client import MatrixClient, Slice, build_search_body
from itamx.request_options import SearchOptions

SLICES = [Slice(origin="JFK", destination="LHR", date="2026-11-19")]


def batch_reply(payload: dict, status: str = "200 OK") -> bytes:
    """A reply shaped like Matrix's: the inner status line inside a 200 envelope."""
    return (
        "--batch_x\r\n"
        "Content-Type: application/http\r\n"
        "Content-ID: <response-batch1+gapiRequest@googleapis.com>\r\n"
        "\r\n"
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n"
        "\r\n"
        f"{json.dumps(payload, indent=2)}\r\n"
        "--batch_x--\r\n"
    ).encode()


def inner_body(request: httpx.Request) -> dict:
    text = request.content.decode()
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


class Recorder:
    """A transport that records each inner body and answers from `reply`."""

    def __init__(self, reply=None):
        self.bodies: list[dict] = []
        self.reply = reply or (
            lambda body: batch_reply(
                {
                    "solutionList": {"solutions": []},
                    "seatChecked": body["inputs"]["checkAvailability"],
                    "solutionSet": "set",
                    "session": "sess",
                }
            )
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = inner_body(request)
        self.bodies.append(body)
        return httpx.Response(200, content=self.reply(body))

    def client(self) -> MatrixClient:
        return MatrixClient(http_client=httpx.Client(transport=httpx.MockTransport(self)))


# --- seat availability -------------------------------------------------------


def test_the_body_asks_for_seats_unless_told_otherwise():
    assert build_search_body(SLICES)["inputs"]["checkAvailability"] is True
    body = build_search_body(SLICES, check_availability=False)
    assert body["inputs"]["checkAvailability"] is False


def test_search_and_detail_send_what_they_are_asked():
    rec = Recorder()
    with rec.client() as c:
        resp = c.search(SLICES, cabin="BUSINESS", cache_ttl=0, check_availability=False)
        c.detail(resp, "s1", SLICES, cabin="BUSINESS", check_availability=False)
    assert [b["inputs"]["checkAvailability"] for b in rec.bodies] == [False, False]


def test_the_cache_never_answers_one_question_with_the_other(monkeypatch):
    # The two asks price different fares -- with seat checking off, a fare
    # nobody can book today still counts -- so they must be two cache entries.
    # They were one when the flag could only be changed after the cache lookup.
    monkeypatch.delenv("ITAMX_NO_CACHE", raising=False)
    rec = Recorder()
    with rec.client() as c:
        checked = c.search(SLICES, cabin="BUSINESS", cache_ttl=3600)
        unchecked = c.search(SLICES, cabin="BUSINESS", cache_ttl=3600, check_availability=False)
        again = c.search(SLICES, cabin="BUSINESS", cache_ttl=3600, check_availability=False)
    assert [b["inputs"]["checkAvailability"] for b in rec.bodies] == [True, False]
    assert checked["seatChecked"] is True
    assert unchecked["seatChecked"] is False
    assert again == unchecked, "the same question is still answered from the cache"


def test_search_options_carry_it_to_both_calls():
    options = SearchOptions(check_availability=False)
    assert options.search_kwargs()["check_availability"] is False
    assert options.detail_kwargs()["check_availability"] is False
    assert SearchOptions().search_kwargs()["check_availability"] is True


# --- the status inside the batch ---------------------------------------------


@pytest.mark.parametrize(
    "status", ["500 Internal Server Error", "502 Bad Gateway", "503 Service Unavailable"]
)
def test_a_server_error_inside_the_batch_raises_like_one_outside(status):
    rec = Recorder(lambda _body: batch_reply({"error": {"code": int(status[:3])}}, status))
    with rec.client() as c, pytest.raises(httpx.HTTPStatusError) as caught:
        c.search(SLICES, cache_ttl=0)
    assert caught.value.response.status_code == int(status[:3])


def test_matrix_refusing_the_request_is_still_returned_as_its_message():
    # Matrix says "no" to a bad request inside a 200 -- a date in the past, an
    # expired session -- and callers read the message from the "error" field.
    refusal = {"error": {"message": "Invalid session id.", "type": "input"}}
    for status in ("200 OK", "400 Bad Request"):
        rec = Recorder(lambda _body, s=status: batch_reply(refusal, s))
        with rec.client() as c:
            assert c.search(SLICES, cache_ttl=0) == refusal
