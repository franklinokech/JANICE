# 8. Use git flow with protected main and develop branches

Date: 2026-11-21

## Status

Accepted

## Context

JANICE deploys `develop` to staging and tagged `main` to production at KWTRP,
and will be maintained by more than one developer.

## Decision

Use git flow branch names (`feature/`, `release/`, `hotfix/`). A ruleset
protects `main` and `develop`: no direct pushes, no force pushes or deletion,
pull requests required, and all CI checks required. Features are squash-merged
into `develop`; releases and hotfixes use merge commits, then `main` is merged
back into `develop`. `git flow feature finish` is not used.

## Consequences

- Nothing reaches staging or production without a pull request and green CI.
- One commit per feature on `develop` keeps history readable and easy to revert.
- Required approvals are 0 while there is a single developer; raise to 1 and
  enable code-owner review when a second developer joins.
