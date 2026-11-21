# 7. Pin CI actions to commit SHAs and automate updates with Dependabot

Date: 2026-11-21

## Status

Accepted

## Context

Version tags on GitHub Actions can be moved to different code by whoever
controls the action's repository, as happened to trivy-action in March 2026.
Pinned versions, however, go stale and miss security fixes.

## Decision

Pin every action to a full commit SHA with the version in a comment, give the
workflow a read-only token, and do not persist checkout credentials.
Dependabot proposes weekly grouped updates for actions, Python, npm, Docker
images and pre-commit hooks, with a 7-day cooldown.

## Consequences

- A compromised tag cannot change what CI runs.
- Updates arrive as pull requests that CI tests before merge.
- Python and Postgres major upgrades, and Node major upgrades, are excluded
  from Dependabot and planned by hand.
