# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Report it privately through GitHub: open the repository's Security tab and choose "Report a vulnerability". Please do not open a public issue for a security problem.

## Scope

In scope:
- the MCP server (`src/analyticsreceipts/server.py`) and the typed refusals it returns;
- the compiler (`src/analyticsreceipts/compiler.py`), including how request values reach the SQL;
- the executor hardening (`src/analyticsreceipts/execution.py`): the read-only connection, disabled external access, locked configuration, resource limits and timeouts.

Out of scope:
- the semantic model file passed with `--model`, and the warehouse passed with `--db`. These are trusted input, chosen by the person who runs the server. Text stored in your own data can still reach the agent; see "Where this breaks" in the README.
- the `fixtures` and `live` harnesses, which run only on your own machine.

There is no promised response time.
