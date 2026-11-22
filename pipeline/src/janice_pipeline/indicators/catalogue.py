"""The indicator catalogue: one definition per indicator, read from dbt.

Each QI indicator is defined once, in its dbt model's YAML (``config.meta``),
next to the SQL that computes it, so the definition and the code cannot drift
apart. This module validates those definitions and renders a readable page per
indicator into docs/indicators/, for the clinical leads to review and approve.
The pages are generated: edit the YAML, then run ``uv run janice-indicators``.
Rules that apply to every indicator live in docs/indicators/README.md.
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PIPELINE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_MODELS_DIR = PIPELINE_DIR / "dbt" / "models" / "qi"
DEFAULT_DOCS_DIR = PIPELINE_DIR.parent / "docs" / "indicators"

GENERATED_MARK = "<!-- Generated"
INDEX_PAGE = "catalogue.md"


class CatalogueError(Exception):
    """An indicator definition is missing, invalid or inconsistent."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Part(_Strict):
    column: str
    description: str


class Reference(_Strict):
    title: str
    url: str | None = None


class Indicator(_Strict):
    indicator_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+$")
    status: Literal["draft", "approved", "retired"]
    approved_by: str | None = None
    approved_on: date | None = None
    unit: str
    type: Literal["outcome", "process", "process_and_outcome"]
    desired_direction: Literal["higher", "lower"]
    definition: str
    numerator: Part
    denominator: Part
    exclusions: list[str] = []
    completeness: str
    breakdowns: list[str] = []
    fields: list[str]
    rationale: str
    references: list[Reference] = []
    model: str = ""  # filled in from the dbt model's name

    @model_validator(mode="after")
    def _approval_is_recorded(self):
        if self.status == "approved" and not (self.approved_by and self.approved_on):
            raise ValueError("an approved indicator needs approved_by and approved_on")
        return self


def load_catalogue(models_dir: Path = DEFAULT_MODELS_DIR) -> list[Indicator]:
    """Every indicator defined in the dbt models under models_dir, by indicator_id."""
    indicators: list[Indicator] = []
    for path in sorted(Path(models_dir).rglob("*.yml")):
        for model in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("models", []):
            meta = (model.get("config") or {}).get("meta") or {}
            if "indicator_id" not in meta:
                continue
            try:
                indicator = Indicator(**meta, model=model["name"])
            except ValidationError as error:
                raise CatalogueError(f"{path}: {model['name']}:\n{error}") from None
            columns = {column["name"] for column in model.get("columns", [])}
            for part in ("numerator", "denominator"):
                column = getattr(indicator, part).column
                if column not in columns:
                    raise CatalogueError(
                        f"{path}: {model['name']}: {part} column {column!r} is not listed "
                        "under the model's columns"
                    )
            indicators.append(indicator)

    ids = [i.indicator_id for i in indicators]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise CatalogueError(f"indicator_id used more than once: {duplicates}")
    return sorted(indicators, key=lambda i: (i.unit, i.indicator_id))


def render_catalogue(indicators: list[Indicator]) -> dict[str, str]:
    """{file name: Markdown} for each indicator's page and the index page."""
    pages = {f"{i.indicator_id}.md": _render_indicator(i) for i in indicators}
    pages[INDEX_PAGE] = _render_index(indicators)
    return pages


def write_catalogue(indicators: list[Indicator], docs_dir: Path = DEFAULT_DOCS_DIR) -> None:
    """Write the generated pages, and remove generated pages for indicators that are gone."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    pages = render_catalogue(indicators)
    for name, text in pages.items():
        (docs_dir / name).write_text(text, encoding="utf-8")
    for old in _generated_files(docs_dir):
        if old.name not in pages:
            old.unlink()


def stale_pages(indicators: list[Indicator], docs_dir: Path = DEFAULT_DOCS_DIR) -> list[str]:
    """Names of pages that are missing, changed by hand, or left over."""
    pages = render_catalogue(indicators)
    stale = {
        name
        for name, text in pages.items()
        if not (docs_dir / name).exists() or (docs_dir / name).read_text("utf-8") != text
    }
    stale |= {p.name for p in _generated_files(docs_dir) if p.name not in pages}
    return sorted(stale)


def _generated_files(docs_dir: Path) -> list[Path]:
    if not docs_dir.exists():
        return []
    return [p for p in docs_dir.glob("*.md") if p.read_text("utf-8").startswith(GENERATED_MARK)]


def _notice(source: str) -> str:
    return (
        f"{GENERATED_MARK} by `uv run janice-indicators` from {source}. "
        "Edit the YAML, not this page. -->\n"
    )


def _status(indicator: Indicator) -> str:
    if indicator.status == "approved":
        return f"Approved by {indicator.approved_by} on {indicator.approved_on.isoformat()}"
    return indicator.status.capitalize()


def _render_indicator(i: Indicator) -> str:
    better = "Higher is better" if i.desired_direction == "higher" else "Lower is better"
    lines = [
        _notice(f"the dbt model `{i.model}`"),
        f"# {i.name}\n",
        "| | |",
        "| --- | --- |",
        f"| Indicator ID | `{i.indicator_id}` |",
        f"| Version | {i.version} |",
        f"| Status | {_status(i)} |",
        f"| Unit | {i.unit.capitalize()} |",
        f"| Type | {i.type.replace('_', ' ').capitalize()} |",
        f"| Direction | {better} |",
        f"| Table | `qi.{i.model}`, one row per site and admission month |",
        "",
        "## Definition\n",
        i.definition.strip() + "\n",
        "## Numerator\n",
        f"{i.numerator.description.strip()} Column: `{i.numerator.column}`.\n",
        "## Denominator\n",
        f"{i.denominator.description.strip()} Column: `{i.denominator.column}`.\n",
    ]
    if i.exclusions:
        lines += ["## Exclusions\n", *[f"- {e.strip()}" for e in i.exclusions], ""]
    lines += ["## Documentation completeness\n", i.completeness.strip() + "\n"]
    if i.breakdowns:
        lines += ["## Breakdowns\n", *[f"- {b.strip()}" for b in i.breakdowns], ""]
    lines += [
        "## REDCap fields\n",
        ", ".join(f"`{f}`" for f in i.fields) + "\n",
        "## Why it matters\n",
        i.rationale.strip() + "\n",
        "## Rules shared by all indicators\n",
        "See [indicator conventions](README.md): suppression, empty rates, "
        "implausible values and completeness.\n",
    ]
    if i.references:
        lines += [
            "## References\n",
            *[f"- [{r.title}]({r.url})" if r.url else f"- {r.title}" for r in i.references],
            "",
        ]
    return "\n".join(lines)


def _render_index(indicators: list[Indicator]) -> str:
    lines = [
        _notice("the dbt models in pipeline/dbt/models/qi"),
        "# Indicator catalogue\n",
        "Every QI indicator JANICE computes. Each page is the indicator's definition, "
        "generated from its dbt model. Shared rules: [indicator conventions](README.md).\n",
        "| Indicator | Unit | Type | Direction | Version | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i in indicators:
        lines.append(
            f"| [{i.name}]({i.indicator_id}.md) | {i.unit.capitalize()} | "
            f"{i.type.replace('_', ' ')} | {i.desired_direction} | {i.version} | {_status(i)} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="janice-indicators",
        description="Render the indicator catalogue (docs/indicators) from the dbt models.",
    )
    parser.add_argument("--check", action="store_true", help="only report stale pages")
    parser.add_argument("--models", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS_DIR)
    args = parser.parse_args(argv)

    try:
        indicators = load_catalogue(args.models)
    except CatalogueError as error:
        print(error, file=sys.stderr)
        return 1
    if args.check:
        stale = stale_pages(indicators, args.docs)
        for name in stale:
            print(f"out of date: {args.docs / name}", file=sys.stderr)
        return 1 if stale else 0
    write_catalogue(indicators, args.docs)
    print(f"Wrote {len(indicators)} indicator pages and the index to {args.docs}")
    return 0
