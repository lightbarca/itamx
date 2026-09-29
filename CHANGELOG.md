# Changelog

## Unreleased

- Added `check_availability` to `MatrixClient.search`, `MatrixClient.detail` and
  `SearchOptions` (default on). Being part of the request body, it is part of the
  cache key, so a no-seat-check search is never answered with a cached seat-checked one.
- A 5xx inside the batch reply now raises `httpx.HTTPStatusError`, as one outside does,
  instead of being returned as data. Matrix's own 4xx refusals are still returned.
- A failed API-key fetch is remembered for an hour, so each new process falls back
  at once instead of fetching the page again.
- Added GitHub Actions CI for lint, tests, compile, locked MCP install, and build.
- Added `itamx mcp-config` for MCP client configuration.
- Added shared Matrix request-building helpers used by both CLI and MCP.
- Added sanitized response fixture tests.
- Replaced the starter package `hello()` with real public exports and version metadata.
- Added core flight service functions and `show_flight_details` MCP tool.
- Added opt-in live smoke tests for Matrix lookup, search, and detail endpoints.

## 0.2.0

- Added `itamx-mcp` and `itamx-mcp-http` MCP entry points.
- Added MCP tools for flight search, date search, location lookup, and airline lookup.
- Added MIT license metadata and README credit for the `fli` project.
