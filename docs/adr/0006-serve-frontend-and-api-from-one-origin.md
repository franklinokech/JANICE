# 6. Serve the frontend and API from one origin through nginx

Date: 2026-11-21

## Status

Accepted

## Context

The Vue app needs to call the Django API. Serving them on different origins
requires CORS configuration and complicates cookies and CSRF.

## Decision

The frontend image runs non-root nginx, which serves the built Vue app and
proxies `/api/` and `/admin/` to the backend. nginx also sets security headers,
a Content-Security-Policy, caching rules and gzip.

## Consequences

- No CORS configuration; one address for users.
- Django receives the original Host header; `ALLOWED_HOSTS` must list every
  public hostname.
- nginx becomes part of the application and is versioned with it.
