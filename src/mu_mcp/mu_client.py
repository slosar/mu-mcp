"""Small, defensive subprocess wrapper around the mu command line tool."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse


class MuError(RuntimeError):
    """A mu command failed or returned output we could not use."""


class MuClient:
    """Call mu without a shell, keeping output and execution time bounded."""

    def __init__(
        self,
        executable: str | None = None,
        muhome: str | None = None,
        timeout: float = 30.0,
        output_limit: int = 8_000_000,
    ) -> None:
        self.executable = executable or os.environ.get("MU_BIN") or shutil.which("mu")
        if not self.executable:
            raise MuError("Could not find 'mu'. Install mu or set MU_BIN to its executable path.")
        self.muhome = muhome or os.environ.get("MUHOME")
        self.timeout = timeout
        self.output_limit = output_limit

    def _run(self, *args: str, max_output: int | None = None) -> str:
        command = [self.executable, "--quiet", "--nocolor"]
        if self.muhome:
            command.extend(["--muhome", self.muhome])
        command.extend(args)
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise MuError(f"mu command timed out after {self.timeout:g} seconds") from exc
        except OSError as exc:
            raise MuError(f"Could not start mu: {exc}") from exc

        limit = max_output or self.output_limit
        if len(result.stdout.encode("utf-8")) > limit:
            raise MuError(f"mu output exceeded the configured {limit}-byte limit")
        # mu uses exit status 2 for an empty result set.
        if result.returncode not in (0, 2):
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise MuError(f"mu command failed: {detail[:1200]}")
        return result.stdout

    def search(self, query: str, limit: int = 20, sort: str = "date", descending: bool = True) -> list[dict[str, Any]]:
        return self._search(query, limit, sort, descending, include_path=False)

    def _search(
        self, query: str, limit: int, sort: str, descending: bool, include_path: bool
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        supported_sort = {"date", "from", "subject", "size"}
        if sort not in supported_sort:
            raise ValueError(f"sort must be one of: {', '.join(sorted(supported_sort))}")

        output = self._run(
            "find", "--format=json", "--maxnum", str(limit), "--sortfield", sort,
            *( ["--reverse"] if descending else [] ), query,
        )
        if not output.strip():
            return []
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise MuError("mu returned invalid JSON from 'mu find'") from exc
        if isinstance(parsed, dict):
            parsed = parsed.get("messages", parsed.get("results", [parsed]))
        if not isinstance(parsed, list):
            raise MuError("mu returned an unexpected JSON result shape")
        return [
            self._public_message(item, include_path=include_path)
            for item in parsed if isinstance(item, dict)
        ]

    @staticmethod
    def _public_message(item: dict[str, Any], include_path: bool = False) -> dict[str, Any]:
        # Keep the result useful to an agent while omitting local paths and any
        # fields mu may add in future that could expose private data.
        aliases = {
            "message-id": "message_id", "message_id": "message_id",
            "date": "date", "from": "from", "to": "to", "cc": "cc",
            "subject": "subject", "flags": "flags", "maildir": "maildir",
            "size": "size", "priority": "priority", "snippet": "snippet",
        }
        result: dict[str, Any] = {}
        for source, target in aliases.items():
            # mu 1.10 encodes its property names with a leading colon (for
            # example, ":subject" and ":message-id"). Accept unprefixed
            # names too for compatibility with other mu versions/wrappers.
            key = f":{source}" if f":{source}" in item else source
            if key in item and target not in result:
                result[target] = MuClient._normalize_field(target, item[key])
        # Resolve only the file URI/path emitted by mu. It is never accepted
        # as caller-controlled input.
        path = item.get(":path", item.get("path"))
        if include_path and isinstance(path, str):
            result["_mu_path"] = path
        return result

    @staticmethod
    def _normalize_field(name: str, value: Any) -> Any:
        """Turn mu's JSON-LD-ish list values and contact objects into usable metadata."""
        if name in {"from", "to", "cc"} and isinstance(value, list):
            contacts = []
            for contact in value:
                if isinstance(contact, dict):
                    email = contact.get(":email", contact.get("email", ""))
                    display = contact.get(":name", contact.get("name", ""))
                    contacts.append(f"{display} <{email}>" if display and email else email or display)
                else:
                    contacts.append(contact)
            return contacts[0] if len(contacts) == 1 else contacts
        if isinstance(value, list):
            if name == "date" and len(value) >= 2 and all(isinstance(part, int) for part in value):
                # mu 1.10 emits Emacs-style time [high, low, microseconds];
                # newer releases also provide Unix timestamps. Some wrappers
                # use the conventional [year, month, day] representation.
                if len(value) == 3 and 1000 <= value[0] <= 9999 and 1 <= value[1] <= 12 and 1 <= value[2] <= 31:
                    return f"{value[0]:04d}-{value[1]:02d}-{value[2]:02d}"
                if value[0] > 100_000:
                    try:
                        return datetime.fromtimestamp(value[0], timezone.utc).isoformat()
                    except (OverflowError, OSError, ValueError):
                        pass
                if 0 <= value[0] <= 65_535 and 0 <= value[1] <= 65_535:
                    seconds = value[0] * 65_536 + value[1]
                    micros = value[2] if len(value) >= 3 else 0
                    try:
                        return datetime.fromtimestamp(seconds + micros / 1_000_000, timezone.utc).isoformat()
                    except (OverflowError, OSError, ValueError):
                        pass
            return value[0] if len(value) == 1 else value
        return value

    def read(self, query: str, max_chars: int = 12_000) -> dict[str, Any]:
        """Read one matching message. Query syntax is mu's query language."""
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 500 <= max_chars <= 40_000:
            raise ValueError("max_chars must be between 500 and 40000")
        matches = self._search(query, 1, "date", True, include_path=True)
        if not matches:
            return {"found": False, "query": query}
        message = matches[0]
        raw_path = message.pop("_mu_path", None)
        if not isinstance(raw_path, str) or not raw_path:
            raise MuError("mu search result did not include a message path")
        parsed = urlparse(raw_path)
        path = unquote(parsed.path) if parsed.scheme == "file" else raw_path
        output = self._run("view", "--summary-len=1000000", path, max_output=max(self.output_limit, 2_000_000))
        return {"found": True, **message, "body": output[:max_chars], "truncated": len(output) > max_chars}
