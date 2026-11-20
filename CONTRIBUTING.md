# Contributing

## Branching (git flow)

- `main`: released code only; every merge is tagged (`v1.2.0`).
- `develop`: integration branch; deploys to staging.
- Feature work: `git flow feature start <name>`, then
  `git flow feature publish <name>` and open a pull request into `develop`.
- Do not run `git flow feature finish`: `develop` only accepts pull requests.

## Starting new work

```bash
git checkout develop
git pull
git flow feature start <short-name>
```

## Pull requests

- Base branch: `develop` (never `main` for features).
- Fill in the pull request template.
- Merge with **Squash and merge**; delete the branch afterwards.
- Releases and hotfixes merge into `main` with **Create a merge commit**,
  then `main` is merged back into `develop`.

## Commit messages

Use conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.

## Definition of done

Tests written first and passing, CI green, no secrets or patient data,
documentation updated, demoed on staging.
