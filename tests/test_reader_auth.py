import pytest
from fastapi import HTTPException
from starlette.requests import Request

from bintu_api.reader_auth import reader_owner
from bintu_api.settings import Settings


MASTER = "reader-test-master"
PROXY = "reader-test-proxy"
SCOPED = "reader-test-mcp"


def settings(**overrides):
    values = dict(
        api_key=MASTER,
        rapidapi_proxy_secret=PROXY,
        mcp_api_key=SCOPED,
        require_auth=True,
    )
    values.update(overrides)
    return Settings(**values)


def request(headers=None, host="127.0.0.1"):
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (name.lower().encode("ascii"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ],
        "client": (host, 1234),
    })


def test_direct_key_owner_is_stable_and_hides_key():
    headers = {"X-API-Key": MASTER}
    first = reader_owner(request(headers), settings())
    second = reader_owner(request(headers, host="192.0.2.1"), settings())

    assert first == second
    assert first.startswith("reader:apikey:")
    assert MASTER not in first


@pytest.mark.parametrize("key", ["wrong-key", SCOPED, ""])
def test_rejects_invalid_or_mcp_only_key(key):
    with pytest.raises(HTTPException) as error:
        reader_owner(request({"X-API-Key": key}), settings())

    assert error.value.status_code == 401


def test_rejects_open_mode_without_credentials():
    config = settings(
        api_key="",
        rapidapi_proxy_secret="",
        mcp_api_key="",
        require_auth=False,
    )

    with pytest.raises(HTTPException) as error:
        reader_owner(request(), config)

    assert error.value.status_code == 401
    assert error.value.detail["code"] == "reader_auth_required"


def test_strict_misconfiguration_still_fails_closed():
    config = settings(api_key="", rapidapi_proxy_secret="")

    with pytest.raises(HTTPException) as error:
        reader_owner(request(), config)

    assert error.value.status_code == 500


def test_verified_gateway_subscribers_have_distinct_owners():
    owners = []
    for user in ["subscriber-one", "subscriber-two"]:
        owner = reader_owner(request({
            "X-RapidAPI-Proxy-Secret": PROXY,
            "X-RapidAPI-User": user,
        }), settings())
        assert owner.startswith("reader:rapidapi:")
        assert user not in owner
        assert PROXY not in owner
        owners.append(owner)

    assert owners[0] != owners[1]


@pytest.mark.parametrize(
    "user",
    ["", " ", "x" * 257, "user name", "user\tname", "\u00e9"],
)
def test_rejects_invalid_verified_subscriber(user):
    with pytest.raises(HTTPException) as error:
        reader_owner(request({
            "X-RapidAPI-Proxy-Secret": PROXY,
            "X-RapidAPI-User": user,
        }), settings())

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "reader_identity_required"


def test_verified_proxy_requires_subscriber_even_with_valid_direct_key():
    with pytest.raises(HTTPException) as error:
        reader_owner(request({
            "X-RapidAPI-Proxy-Secret": PROXY,
            "X-API-Key": MASTER,
        }), settings())

    assert error.value.status_code == 403


def test_unverified_gateway_headers_do_not_change_direct_owner():
    plain = reader_owner(
        request({"X-API-Key": MASTER}),
        settings(),
    )
    spoofed = reader_owner(request({
        "X-API-Key": MASTER,
        "X-RapidAPI-Proxy-Secret": "wrong-proxy",
        "X-RapidAPI-User": "someone-else",
    }), settings())

    assert spoofed == plain


def test_subscriber_header_alone_cannot_authenticate():
    with pytest.raises(HTTPException) as error:
        reader_owner(request({
            "X-RapidAPI-User": "subscriber-one",
        }), settings())

    assert error.value.status_code == 401


def test_distinct_direct_keys_have_distinct_owner_namespaces():
    first = reader_owner(
        request({"X-API-Key": MASTER}),
        settings(),
    )
    other = "reader-test-other-master"
    second = reader_owner(
        request({"X-API-Key": other}),
        settings(api_key=other),
    )

    assert first != second
