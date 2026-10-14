# mu-mcp

A small, read-only [Model Context Protocol](https://modelcontextprotocol.io/)
server that lets agents search and read a local Maildir indexed by
[mu](https://www.djcbsoftware.nl/code/mu/). It exposes two tools:

- `search_mail`: search with mu's query language, returning bounded message metadata.
- `read_mail`: read one matching message as plain text, with a configurable output cap.

This connector does not send, delete, move, flag, or otherwise modify mail.

## Requirements

- Python 3.10 or later
- [mu](https://www.djcbsoftware.nl/code/mu/) installed and initialized/indexed for the account you want to use
- An MCP client that supports local stdio servers

## Install

From a checkout:

```sh
python -m pip install .
```

Or run directly from the repository with `python -m mu_mcp.server` after
installing the package. For development, install `python -m pip install -e
'.[dev]'`.

## Configure an MCP client

The server communicates over stdio. Example configuration for clients that use
the common `mcpServers` format:

```json
{
  "mcpServers": {
    "mu-mail": {
      "command": "mu-mcp",
      "env": {
        "MUHOME": "/home/you/.mu",
        "MU_BIN": "/usr/bin/mu"
      }
    }
  }
}
```

`MUHOME` and `MU_BIN` are optional. `MUHOME` is passed to mu as `--muhome`;
otherwise mu's normal configuration and `MUHOME` environment behavior apply.
`MU_MCP_TIMEOUT` sets the per-command timeout in seconds (default `30`).
Keep stdout reserved for MCP: diagnostics are returned as tool errors.

## Tools

### `search_mail(query, limit=20, sort="date", descending=true)`

Accepts native mu query syntax. Examples:

```text
from:alice@example.com subject:invoice
after:2025-01-01 before:2025-02-01
flag:unread
"project aurora" AND to:team@example.com
```

At most 100 results are allowed. Sorting is restricted to `date`, `from`,
`subject`, or `size`. Results include common headers, flags, and message IDs;
local filesystem paths are intentionally omitted.

### `read_mail(query, max_chars=12000)`

Finds one matching result and asks `mu view` for its headers and plain-text
content. Use a discriminating query, such as `message-id:<id>`, sender plus
subject, and/or a date range. `max_chars` must be between 500 and 40,000.
The result includes a `truncated` flag. Attachments are not extracted.

## Privacy and safety

Email content is sensitive. This server runs locally and returns message data
only to the connected MCP client, but that client or its model provider may
process tool results under its own policies. Connect only clients you trust.
Queries are passed as argument values directly to `mu` without a shell, and
the server has no mail mutation tools. Message paths come from mu search
results and are not accepted as user-provided filesystem paths.

## Development

```sh
python -m pip install -e '.[dev]'
pytest
```

Tests mock the `mu` process and do not read your mailbox. See
[mu's query syntax](https://www.djcbsoftware.nl/code/mu/mu.html#Search-Queries)
for the full search language.

## License

MIT. See [LICENSE](LICENSE).
