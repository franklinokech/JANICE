# 3. Split Django settings by environment, with secrets from the environment

Date: 2026-11-21

## Status

Accepted

## Context

A single `settings.py` mixes development conveniences (DEBUG, a hard-coded
secret key) with production needs, and makes it easy to run a server with
unsafe settings.

## Decision

Use `janice/settings/{base,dev,test,prod}.py`. `manage.py` defaults to `dev`;
`asgi.py` and `wsgi.py` default to `prod`. Production settings read every
secret from environment variables and refuse to start if one is missing.

## Consequences

- A server cannot silently start with development settings.
- Secrets never appear in the repository.
- Locally, secrets live in a git-ignored `.env`; `.env.example` documents them.
- Admin login needs HTTPS in production settings (secure cookies), so it does
  not work over plain HTTP locally.
