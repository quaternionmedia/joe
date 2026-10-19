"""Requests a browser was made to send from another site, refused before routing.

A page open in a browser on this machine can make the browser send requests
to joe on loopback; one whose name is re-pointed at 127.0.0.1 -- DNS rebinding
-- can read the answers too. joe has no authentication, so `Modules.Access.Guard`
refuses: a Host it does not answer to, a state-changing request from another
site's page (Origin), anything the browser marks cross-site (Sec-Fetch-Site)
other than following a link, and a JSON route's body sent as a form or as
text. Clients that are not browsers send none of these headers.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

import api
from Modules import Access
from Modules.Control import Control
from Modules.Conversation import Conversation

EVIL = "https://evil.example"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """The state a refused request must leave alone, fresh for each test; and
    no host name added to the ones joe answers to."""
    monkeypatch.setattr(api, "control", Control())
    monkeypatch.setattr(api, "conversation", Conversation())
    monkeypatch.delenv(Access.HOSTS_SETTING, raising=False)
    monkeypatch.delenv(Access.ORIGINS_SETTING, raising=False)


@pytest.fixture
def client():
    """As curl or vox would ask: joe on loopback, no browser headers."""
    return TestClient(api.app, base_url="http://127.0.0.1:8010")


def answer(client, **headers):
    return client.post("/api/voice/answer", json={"text": "approve"}, headers=headers)


def answered() -> bool:
    return api.control.snapshot()["answer_waiting"]


# ─── Host ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host, name", [
    ("localhost:8000", "localhost"), ("LOCALHOST.:8000", "localhost"), ("[::1]:8010", "::1"),
    ("127.0.0.1", "127.0.0.1"), ("joe.lan:8010", "joe.lan"), ("joe.lan:abc", "joe.lan:abc"),
])
def test_a_host_header_is_read_without_its_port(host, name):
    assert Access.host_name(host) == name


@pytest.mark.parametrize("host", [
    "localhost", "localhost:8010", "studio.localhost:3000", "127.0.0.1:8010", "[::1]:8010",
    "172.17.0.1:8010", "192.168.1.5", "host.docker.internal:8010", "HOST.DOCKER.INTERNAL",
])
def test_joe_answers_to_loopback_addresses_and_docker_s_name_for_the_host(host):
    assert Access.host_allowed(host, {})


@pytest.mark.parametrize("host", [
    "evil.example", "evil.example:8010", "localhost.evil.example", "127.0.0.1.nip.io", "", "joe",
])
def test_joe_answers_to_no_other_name_unless_told(host):
    assert not Access.host_allowed(host, {})


def test_joe_answers_to_the_names_in_its_setting():
    env = {Access.HOSTS_SETTING: " Joe , studio.lan"}

    assert Access.host_allowed("joe:8010", env)
    assert Access.host_allowed("studio.lan", env)
    assert not Access.host_allowed("evil.example", env)


@pytest.mark.parametrize("host", ["evil.example:8010", "rebind.attacker.example"])
def test_a_request_under_a_name_joe_does_not_answer_to_is_refused(client, host):
    """DNS rebinding: a page re-pointed at 127.0.0.1 still sends its own name."""
    response = client.get("/api/voice/control", headers={"host": host})

    assert response.status_code == 400
    assert response.json()["detail"].startswith(f"joe does not answer to the host {Access.host_name(host)!r}")
    assert "JOE_ALLOWED_HOSTS" in response.json()["detail"]
    assert answer(client, host=host).status_code == 400
    assert not answered()


@pytest.mark.parametrize("host", [
    "127.0.0.1:8010", "localhost:8010", "[::1]:8010", "host.docker.internal:8010", "172.17.0.1:8010",
])
def test_alfred_vox_and_curl_are_answered_wherever_they_reach_joe(client, host):
    """Loopback; Docker Desktop's name for the host; docker0's address on Linux."""
    assert client.get("/api/media/capabilities", headers={"host": host}).status_code == 200
    gone = client.delete("/api/media/0123456789abcdef0123456789abcdef", headers={"host": host})
    assert gone.status_code == 404


def test_a_name_in_the_setting_is_answered(monkeypatch):
    monkeypatch.setenv(Access.HOSTS_SETTING, "joe")
    client = TestClient(api.app, base_url="http://joe:8010")

    assert client.get("/api/health").status_code == 200


# ─── Origin ───────────────────────────────────────────────────────────────────

def test_a_page_on_another_site_cannot_answer_a_question(client):
    response = answer(client, origin=EVIL)

    assert response.status_code == 403
    assert response.json()["detail"].startswith(f"joe takes no request from a page at {EVIL!r}")
    assert "JOE_ALLOWED_ORIGINS" in response.json()["detail"]
    assert not answered()


@pytest.mark.parametrize("origin", ["null", "http://localhost:5173", "http://127.0.0.1:9999", "file://"])
def test_no_other_page_on_this_machine_can_either(client, origin):
    assert answer(client, origin=origin).status_code == 403
    assert not answered()


def test_joe_s_dev_page_can(client):
    """Straight to the API, as the page does when Vite's proxy is not used."""
    assert answer(client, origin="http://localhost:3000").status_code == 200
    assert answered()


def test_joe_s_dev_page_can_through_vite_s_proxy():
    """The proxy keeps the page's Host: the Origin is the Host's own page."""
    client = TestClient(api.app, base_url="http://127.0.0.1:18405")

    assert answer(client, origin="http://127.0.0.1:18405").status_code == 200


def test_a_page_joe_itself_serves_can(client):
    """FastAPI's /docs, asking the server it came from."""
    assert answer(client, origin="http://127.0.0.1:8010").status_code == 200


def test_a_page_in_the_setting_can_ask_and_read_the_answer(client, monkeypatch):
    monkeypatch.setenv(Access.ORIGINS_SETTING, "https://studio.example")

    response = answer(client, origin="https://studio.example")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://studio.example"
    preflight = client.options("/api/voice/answer", headers={
        "origin": "https://studio.example", "access-control-request-method": "POST",
        "access-control-request-headers": "content-type"})
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://studio.example"


def test_a_page_on_another_site_is_never_let_read_an_answer(client):
    """A GET is answered -- it changes nothing -- but without the header that
    would let the page read it."""
    response = client.get("/api/voice/control", headers={"origin": EVIL})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_no_preflight_from_another_site_is_granted(client):
    preflight = client.options("/api/media", headers={
        "origin": EVIL, "access-control-request-method": "POST",
        "access-control-request-headers": "content-type"})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


def test_a_private_network_access_preflight_is_refused(client):
    """Chromium asks before a public page reaches a private address; joe never
    says yes, even to a page it takes requests from."""
    preflight = client.options("/api/voice/answer", headers={
        "origin": "http://localhost:3000", "access-control-request-method": "POST",
        "access-control-request-private-network": "true"})

    assert preflight.status_code == 400
    assert "access-control-allow-private-network" not in preflight.headers


def test_an_upload_from_another_site_s_page_is_refused(client):
    response = client.post("/api/media", content=b"RIFF", headers={
        "origin": EVIL, "content-type": "audio/wav"})

    assert response.status_code == 403


# ─── Sec-Fetch-Site ───────────────────────────────────────────────────────────

def test_a_request_the_browser_marks_cross_site_is_refused_without_an_origin(client):
    """A form posted from another site whose Origin was stripped on the way."""
    response = answer(client, **{"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate"})

    assert response.status_code == 403
    assert "Sec-Fetch-Site" in response.json()["detail"]
    assert not answered()


def test_another_site_cannot_embed_a_recording(client):
    """`<audio src>` on another site's page: a cross-site GET that is no navigation."""
    response = client.get("/api/voice/control", headers={
        "sec-fetch-site": "cross-site", "sec-fetch-mode": "no-cors", "sec-fetch-dest": "audio"})

    assert response.status_code == 403


def test_following_a_link_from_another_site_is_answered(client):
    response = client.get("/api/health", headers={
        "sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate"})

    assert response.status_code == 200


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_a_request_from_this_site_or_the_address_bar_is_answered(client, site):
    assert answer(client, **{"sec-fetch-site": site}).status_code == 200


# ─── JSON bodies ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", [
    "text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=x", None,
])
@pytest.mark.parametrize("path, body", [
    ("/api/voice/answer", b'{"text": "approve"}'),
    ("/api/voice/hold", b'{"held": true}'),
    ("/api/voice/conversation", b'{"state": "speaking", "text": "Approve?"}'),
    ("/api/voice/strike", b'{"take": "t", "last": true}'),
])
def test_a_json_route_takes_only_a_json_body(client, path, body, kind):
    """What a form, or `fetch` with no preflight, can send holds no JSON type."""
    headers = {"content-type": kind} if kind else {}
    response = client.post(path, content=body, headers=headers)

    assert response.status_code == 415
    assert response.json() == {"detail": "the body must be JSON, sent as Content-Type: application/json"}
    assert not answered()
    assert api.conversation.snapshot()["events"] == []
    assert api.control.snapshot()["held"] is False


@pytest.mark.parametrize("kind", ["application/json", "application/json; charset=utf-8",
                                  "application/vnd.joe+json"])
def test_a_json_body_sent_as_json_is_taken(client, kind):
    response = client.post("/api/voice/answer", content=b'{"text": "approve"}',
                           headers={"content-type": kind})

    assert response.status_code == 200


# ─── The settings ─────────────────────────────────────────────────────────────

def test_judge_refuses_nothing_a_plain_client_sends():
    assert Access.judge("POST", Headers({"host": "127.0.0.1:8010"}), {}) is None
    assert Access.judge("DELETE", Headers({}), {}) is None


def test_a_listed_host_or_origin_that_cannot_be_one_is_a_problem():
    found = Access.problems({Access.HOSTS_SETTING: "http://joe, joe:8010, joe",
                             Access.ORIGINS_SETTING: "studio.example, https://ok.example, https://x.example/path"})

    assert found == [
        "JOE_ALLOWED_HOSTS lists 'http://joe', which is not a host name: give names without a scheme or a port",
        "JOE_ALLOWED_HOSTS lists 'joe:8010', which is not a host name: give names without a scheme or a port",
        ("JOE_ALLOWED_ORIGINS lists 'studio.example', which is not an origin: give scheme://host[:port], "
         "as a browser sends it"),
        ("JOE_ALLOWED_ORIGINS lists 'https://x.example/path', which is not an origin: give "
         "scheme://host[:port], as a browser sends it"),
    ]


def test_the_banner_names_what_else_joe_answers_to():
    lines = Access.banner({Access.HOSTS_SETTING: "joe", Access.ORIGINS_SETTING: "https://studio.example"})

    assert "joe: also answers to the host names joe (JOE_ALLOWED_HOSTS)" in lines
    assert "joe: also takes requests from pages at https://studio.example (JOE_ALLOWED_ORIGINS)" in lines
    assert not any("also" in line for line in Access.banner({}))
