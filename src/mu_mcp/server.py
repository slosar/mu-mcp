"""MCP stdio server exposing read-only mu search and message reading."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .mu_client import MuClient, MuError

mcp = FastMCP("mu-mail")


def _client() -> MuClient:
    timeout = float(os.environ.get("MU_MCP_TIMEOUT", "30"))
    return MuClient(timeout=timeout)


@mcp.tool()
def search_mail(query: str, limit: int = 20, sort: str = "date", descending: bool = True) -> list[dict]:
    """Search the local mu-indexed mailbox using mu query syntax.

    Examples: "from:alice@example.com subject:invoice", "after:2025-01-01
    before:2025-02-01", or "flag:unread". Returns at most 100 metadata
    records; local filesystem paths are excluded.
    """
    try:
        return _client().search(query, limit=limit, sort=sort, descending=descending)
    except (MuError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def read_mail(query: str, max_chars: int = 12_000) -> dict:
    """Read the first message matching a mu query; message output is truncated.

    Use a specific query such as "message-id:abc@example.com" or combine
    sender, subject, and date terms to identify the intended email. Returns
    headers and plain-text content. This tool does not modify the mailbox.
    """
    try:
        return _client().read(query, max_chars=max_chars)
    except (MuError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def main() -> None:
    """Run the server over stdio, as expected by MCP clients."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
