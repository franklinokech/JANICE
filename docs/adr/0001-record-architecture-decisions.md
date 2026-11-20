# 1. Record architecture decisions

Date: 2026-11-20

## Status

Accepted

## Context

JANICE will be maintained by developers other than its first author, and
evaluated in a research paper. The reasons behind design choices need to
survive beyond chat threads and memory.

## Decision

We record each significant architectural decision as a short Markdown file in
`docs/adr/`, numbered in order, using the format: Context, Decision,
Consequences. Superseded ADRs are kept and marked as superseded.

## Consequences

- New developers can read why things are the way they are.
- Each ADR is reviewed in the same pull request as the change it describes.
- Small overhead per decision (about 15 minutes).
