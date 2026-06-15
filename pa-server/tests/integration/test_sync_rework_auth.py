"""WP-4 integration tests — deployment-driven Cloud/DC auth + endpoint + paging
(design §4.2 step 3; contract-map integration_points jira_cloud_and_datacenter +
confluence_cloud_and_datacenter, kind http_api).

These exercise pa_core.jira_fetch / confluence_fetch at the HTTP boundary WITHOUT
a network: the stdlib `urllib.request.urlopen` is intercepted so we can assert the
exact Authorization scheme, endpoint path, and paging parameter the deployment
discriminator selects. The auth payloads are the ones the jira-rest-api +
confluence-rest-api skills prescribe:

  * Cloud Jira       -> Basic (email:token, b64) + GET /rest/api/3/search/jql +
                        nextPageToken cursor (classic /search removed from Cloud 2025).
  * Data Center Jira -> PAT Bearer + GET /rest/api/2/search + startAt/maxResults.
  * Cloud Confluence -> Basic + GET /rest/api/search (CQL; no v2 equivalent).
  * DC Confluence    -> Bearer + GET /rest/api/search (CQL).

stdlib + pytest only; no new pip deps (AMY D-plus lock).
"""
import base64
import io
import json
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest

PA_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent
PA_CORE_PATH = PA_SERVER_ROOT / "pa_core.py"


def _load(name, path):
    loader = SourceFileLoader(name, str(path))
    spec = spec_from_loader(name, loader)
    mod = module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pa_core():
    return _load("pa_core", PA_CORE_PATH)


class _FakeResp:
    """Minimal context-manager response mimicking urllib's HTTPResponse."""

    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._bytes


class _Capture:
    """Records every urlopen Request and replays a queue of canned responses."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.requests = []  # list of (url, headers)

    def __call__(self, req, timeout=None):
        # req is a urllib.request.Request — capture full URL + headers.
        self.requests.append((req.full_url, dict(req.header_items())))
        payload = self._pages.pop(0) if self._pages else {}
        return _FakeResp(payload)


def _install(monkeypatch, pa_core, pages):
    cap = _Capture(pages)
    monkeypatch.setattr(pa_core.urllib.request, "urlopen", cap)
    return cap


# ===========================================================================
# Jira — Cloud vs Data Center
# ===========================================================================

class TestJiraAuthAndEndpoint:
    def test_cloud_uses_basic_auth_and_search_jql_endpoint(self, pa_core, monkeypatch):
        monkeypatch.setenv("JIRA_USER", "me@example.com")
        cap = _install(monkeypatch, pa_core, pages=[{"issues": [{"key": "A-1"}]}])  # no nextPageToken
        issues = pa_core.jira_fetch(
            "https://acme.atlassian.net", "api-token", "jql",
            "assignee = currentUser()", deployment="cloud", user_env="JIRA_USER",
        )
        assert [i["key"] for i in issues] == ["A-1"]
        url, headers = cap.requests[0]
        # Endpoint: Cloud /rest/api/3/search/jql
        assert urlparse(url).path == "/rest/api/3/search/jql"
        # Auth: Basic <b64(email:token)>
        auth = headers.get("Authorization", "")
        assert auth.startswith("Basic ")
        decoded = base64.b64decode(auth.split(" ", 1)[1]).decode()
        assert decoded == "me@example.com:api-token"

    def test_cloud_follows_nextpagetoken_cursor(self, pa_core, monkeypatch):
        monkeypatch.setenv("JIRA_USER", "me@example.com")
        cap = _install(monkeypatch, pa_core, pages=[
            {"issues": [{"key": "A-1"}], "nextPageToken": "CURSOR2"},
            {"issues": [{"key": "A-2"}]},  # no token -> stop
        ])
        issues = pa_core.jira_fetch(
            "https://acme.atlassian.net", "tok", "jql", "x",
            deployment="cloud", user_env="JIRA_USER",
        )
        assert [i["key"] for i in issues] == ["A-1", "A-2"]
        assert len(cap.requests) == 2
        # Second request carries the nextPageToken from page 1.
        q = parse_qs(urlparse(cap.requests[1][0]).query)
        assert q.get("nextPageToken") == ["CURSOR2"]

    def test_datacenter_uses_bearer_and_v2_search_with_startat(self, pa_core, monkeypatch):
        cap = _install(monkeypatch, pa_core, pages=[
            {"issues": [{"key": "D-1"}], "total": 1},
        ])
        issues = pa_core.jira_fetch(
            "https://jira.corp.local", "pat-token", "jql", "x",
            deployment="datacenter",
        )
        assert [i["key"] for i in issues] == ["D-1"]
        url, headers = cap.requests[0]
        assert urlparse(url).path == "/rest/api/2/search"
        assert headers.get("Authorization") == "Bearer pat-token"
        q = parse_qs(urlparse(url).query)
        assert q.get("startAt") == ["0"]
        assert q.get("maxResults") == ["50"]

    def test_datacenter_pages_by_startat_until_total(self, pa_core, monkeypatch):
        # 2 items across 2 pages of size... we simulate a short final page.
        cap = _install(monkeypatch, pa_core, pages=[
            {"issues": [{"key": f"D-{i}"} for i in range(50)], "total": 51},
            {"issues": [{"key": "D-50"}], "total": 51},
        ])
        issues = pa_core.jira_fetch(
            "https://jira.corp.local", "pat", "jql", "x", deployment="datacenter",
        )
        assert len(issues) == 51
        # Page 2 advanced startAt to 50.
        q = parse_qs(urlparse(cap.requests[1][0]).query)
        assert q.get("startAt") == ["50"]


# ===========================================================================
# Confluence — Cloud vs Data Center (auth differs; CQL endpoint shared)
# ===========================================================================

class TestConfluenceAuth:
    def test_cloud_uses_basic_auth_on_cql_search(self, pa_core, monkeypatch):
        monkeypatch.setenv("CONF_USER", "me@example.com")
        cap = _install(monkeypatch, pa_core, pages=[{"results": [{"id": "1"}]}])
        results = pa_core.confluence_fetch(
            "https://acme.atlassian.net/wiki", "token", "label", "team-x",
            deployment="cloud", user_env="CONF_USER",
        )
        assert [r["id"] for r in results] == ["1"]
        url, headers = cap.requests[0]
        assert urlparse(url).path.endswith("/rest/api/search")
        auth = headers.get("Authorization", "")
        assert auth.startswith("Basic ")
        assert base64.b64decode(auth.split(" ", 1)[1]).decode() == "me@example.com:token"
        # CQL is built from the label strategy.
        q = parse_qs(urlparse(url).query)
        assert 'label = "team-x"' in q.get("cql", [""])[0]

    def test_datacenter_uses_bearer_on_cql_search(self, pa_core, monkeypatch):
        cap = _install(monkeypatch, pa_core, pages=[{"results": [{"id": "9"}]}])
        results = pa_core.confluence_fetch(
            "https://wiki.corp.local", "pat", "cql", 'type = "page"',
            deployment="datacenter",
        )
        assert [r["id"] for r in results] == ["9"]
        url, headers = cap.requests[0]
        assert headers.get("Authorization") == "Bearer pat"
        q = parse_qs(urlparse(url).query)
        assert q.get("expand") == ["version,body.storage"]


# ===========================================================================
# Error mapping: a 401 from the boundary surfaces as a typed SyncError
# ===========================================================================

class TestAuthErrorMapping:
    def test_http_401_becomes_sync_error(self, pa_core, monkeypatch):
        import urllib.error

        def boom(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))

        monkeypatch.setattr(pa_core.urllib.request, "urlopen", boom)
        with pytest.raises(pa_core.SyncError):
            pa_core.jira_fetch("https://x", "bad", "jql", "x", deployment="datacenter")
