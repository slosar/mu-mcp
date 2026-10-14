import json
import subprocess

import pytest

from mu_mcp.mu_client import MuClient, MuError


def client_with(monkeypatch, stdout="[]", returncode=0):
    monkeypatch.setattr("mu_mcp.mu_client.shutil.which", lambda _: "/usr/bin/mu")
    client = MuClient()
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    monkeypatch.setattr("mu_mcp.mu_client.subprocess.run", run)
    return client, seen


def test_search_uses_json_bounded_results_and_hides_path(monkeypatch):
    result = [{"subject": "Invoice", "from": "a@example.com", "path": "/mail/a", "message-id": "x"}]
    client, seen = client_with(monkeypatch, json.dumps(result))
    found = client.search("subject:invoice", limit=5)
    assert found == [{"message_id": "x", "from": "a@example.com", "subject": "Invoice"}]
    assert seen[0][1:4] == ["--quiet", "--nocolor", "find"]
    assert "--maxnum" in seen[0] and "5" in seen[0]


def test_search_normalizes_mu_110_colon_keys_and_contacts(monkeypatch):
    result = [{
        ":subject": "Impedance test", ":from": [{":name": "A Person", ":email": "a@example.com"}],
        ":date": [2025, 4, 9], ":message-id": "m@example.com", ":flags": ["unread"],
        ":path": "/mail/message",
    }]
    client, _ = client_with(monkeypatch, json.dumps(result))
    assert client.search("impedance") == [{
        "subject": "Impedance test", "from": "A Person <a@example.com>",
        "date": "2025-04-09", "message_id": "m@example.com", "flags": "unread",
    }]


def test_search_normalizes_mu_timestamp_date(monkeypatch):
    client, _ = client_with(monkeypatch, json.dumps([{":date": [1_700_000_000, 0, 0]}]))
    assert client.search("impedance")[0]["date"] == "2023-11-14T22:13:20+00:00"


def test_search_normalizes_mu_emacs_time_date(monkeypatch):
    client, _ = client_with(monkeypatch, json.dumps([{":date": [27241, 12345, 100000]}]))
    assert client.search("impedance")[0]["date"] == "2026-07-28T22:42:01.100000+00:00"


def test_empty_result_exit_code_is_success(monkeypatch):
    client, _ = client_with(monkeypatch, "", returncode=2)
    assert client.search("from:nobody") == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"sort": "path"}])
def test_search_validates_options(monkeypatch, kwargs):
    client, _ = client_with(monkeypatch)
    with pytest.raises(ValueError):
        client.search("hello", **kwargs)


def test_invalid_json_is_reported(monkeypatch):
    client, _ = client_with(monkeypatch, "not json")
    with pytest.raises(MuError, match="invalid JSON"):
        client.search("hello")


def test_subprocess_failure_is_bounded_and_reported(monkeypatch):
    client, _ = client_with(monkeypatch, "", returncode=1)
    monkeypatch.setattr("mu_mcp.mu_client.subprocess.run", lambda *a, **kw: subprocess.CompletedProcess([], 1, "", "database issue"))
    with pytest.raises(MuError, match="database issue"):
        client.search("hello")


def test_read_uses_result_path_and_truncates_body(monkeypatch):
    result = json.dumps([{":subject": "Notes", ":path": "file:///mail/notes", ":message-id": "m1"}])
    client, seen = client_with(monkeypatch, result)
    def run(command, **kwargs):
        seen.append(command)
        if "find" in command:
            return subprocess.CompletedProcess(command, 0, result, "")
        return subprocess.CompletedProcess(command, 0, "Subject: Notes\n" + "x" * 700, "")
    monkeypatch.setattr("mu_mcp.mu_client.subprocess.run", run)
    value = client.read("message-id:m1", max_chars=500)
    assert value["body"] == "Subject: Notes\n" + "x" * (500 - len("Subject: Notes\n"))
    assert value["truncated"] is True
    assert seen[-1][-1] == "/mail/notes"


def test_read_no_match(monkeypatch):
    client, _ = client_with(monkeypatch, "[]")
    assert client.read("from:nobody") == {"found": False, "query": "from:nobody"}
