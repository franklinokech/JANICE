"""The project registry: which REDCap projects JANICE stages, and how.

Projects are listed in projects.yaml (next to this file), so adding, changing
or disabling one is a reviewed pull request. Set JANICE_PROJECTS_FILE to use a
different file. The registry holds no secrets: each project names the
environment variable that holds its token (default REDCAP_TOKEN_<KEY>).

Every setting is checked when the file is loaded, so a mistake fails loudly
when Dagster starts instead of quietly mid-run. Unknown settings are refused:
a misspelt "keep_in_cleer" must not be silently ignored.
"""

import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEFAULT_REGISTRY = Path(__file__).with_name("projects.yaml")
REGISTRY_ENV = "JANICE_PROJECTS_FILE"

# A key becomes a table name (raw_<key>) and a file name, so only lowercase
# letters, digits and underscores, starting with a letter
PROJECT_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"


class ProjectRegistryError(Exception):
    """The registry file is missing, unreadable or has an invalid setting."""


class Project(BaseModel):
    """One REDCap project. Only ``key`` and ``site_field`` are required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=PROJECT_KEY_PATTERN)
    site_field: str = Field(min_length=1)
    description: str = ""
    keep_in_clear: tuple[str, ...] = ()
    token_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    api_url: str | None = None
    server_timezone: str = "UTC"
    dictionary_file: str | None = None
    enabled: bool = True

    @field_validator("api_url")
    @classmethod
    def _https_only(cls, url: str | None) -> str | None:
        if url is not None and urlparse(url).scheme != "https":
            raise ValueError("api_url must use https, so the token is never sent in clear")
        return url

    @field_validator("server_timezone")
    @classmethod
    def _known_time_zone(cls, name: str) -> str:
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {name!r}") from None
        return name

    @property
    def token_variable(self) -> str:
        """Name of the environment variable holding this project's API token."""
        return self.token_env or f"REDCAP_TOKEN_{self.key.upper()}"

    @property
    def dictionary_filename(self) -> str:
        """Data dictionary used for synthetic records on laptops and in CI."""
        return self.dictionary_file or f"{self.key}_dictionary.csv"

    @property
    def clear_fields(self) -> set[str]:
        """Flagged fields that are not hashed: the site field, plus any listed."""
        return {self.site_field, *self.keep_in_clear}


class _Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[Project]


def load_projects(path: Path | None = None) -> list[Project]:
    """The enabled projects, in file order."""
    path = Path(path or os.environ.get(REGISTRY_ENV) or DEFAULT_REGISTRY)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        registry = _Registry.model_validate(raw)
    except OSError as error:
        raise ProjectRegistryError(f"Cannot read project registry {path}: {error}") from None
    except yaml.YAMLError as error:
        raise ProjectRegistryError(f"{path} is not valid YAML: {error}") from None
    except ValidationError as error:
        raise ProjectRegistryError(f"{path} has invalid settings:\n{error}") from None

    keys = [p.key for p in registry.projects]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise ProjectRegistryError(f"{path}: project keys used more than once: {duplicates}")

    enabled = [p for p in registry.projects if p.enabled]
    if not enabled:
        raise ProjectRegistryError(f"{path} has no enabled projects")
    return enabled
