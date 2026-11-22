"""The nightly run.

At 02:00 Nairobi time the schedule starts ingest_project once per registered
project (REDCap -> hashed staging -> Postgres). Sites sync to the pooled
REDCap during the day, so by then the day's records are in.

A sensor then waits until every project's run for that night has finished,
and starts build_warehouse_models once, so the indicators are rebuilt from
all projects together. A failed project does not hold the others back: its
load is all-or-nothing, so its previous rows stay in place.

Both are off by default, so a laptop never starts runs by itself; servers set
JANICE_SCHEDULES=on.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from janice_pipeline.projects.registry import Project

NIGHTLY_TAG = "janice/nightly"
TIMEZONE = "Africa/Nairobi"
FINISHED = {
    dg.DagsterRunStatus.SUCCESS,
    dg.DagsterRunStatus.FAILURE,
    dg.DagsterRunStatus.CANCELED,
}


def nightly_runs_finished(statuses: Sequence[dg.DagsterRunStatus], expected: int) -> bool:
    """True once every project's nightly run exists and has finished, whatever its result."""
    return len(statuses) >= expected and all(status in FINISHED for status in statuses)


def build_nightly_schedule(projects: list[Project], *, running: bool) -> dg.ScheduleDefinition:
    @dg.schedule(
        name="nightly_ingest",
        job_name="ingest_project",
        cron_schedule="0 2 * * *",
        execution_timezone=TIMEZONE,
        default_status=(
            dg.DefaultScheduleStatus.RUNNING if running else dg.DefaultScheduleStatus.STOPPED
        ),
        description="Stage and load every registered project at 02:00 Nairobi time.",
    )
    def nightly_ingest(context: dg.ScheduleEvaluationContext):
        night = context.scheduled_execution_time.date().isoformat()
        for project in projects:
            yield dg.RunRequest(
                # Same key = same run, so a repeated tick never loads a project twice
                run_key=f"{night}-{project.key}",
                partition_key=project.key,
                tags={NIGHTLY_TAG: night},
            )

    return nightly_ingest


def build_indicators_sensor(
    projects: list[Project],
    *,
    running: bool,
    now: Callable[[], datetime] = lambda: datetime.now(ZoneInfo(TIMEZONE)),
) -> dg.SensorDefinition:
    @dg.sensor(
        name="indicators_after_nightly_ingest",
        job_name="build_warehouse_models",
        minimum_interval_seconds=300,
        default_status=(
            dg.DefaultSensorStatus.RUNNING if running else dg.DefaultSensorStatus.STOPPED
        ),
        description="Rebuild the indicators once every project's nightly load has finished.",
    )
    def indicators_after_nightly_ingest(context: dg.SensorEvaluationContext):
        night = now().astimezone(ZoneInfo(TIMEZONE)).date().isoformat()
        runs = context.instance.get_runs(filters=dg.RunsFilter(tags={NIGHTLY_TAG: night}))
        statuses = [run.status for run in runs]
        if not nightly_runs_finished(statuses, len(projects)):
            done = sum(status in FINISHED for status in statuses)
            return dg.SkipReason(f"Night {night}: {done} of {len(projects)} project loads finished")
        failed = sorted(
            run.tags.get("dagster/partition", "?")
            for run in runs
            if run.status != dg.DagsterRunStatus.SUCCESS
        )
        if failed:
            context.log.warning(f"Night {night}: loads failed for {failed}; rebuilding anyway")
        # One build per night, however many times the sensor ticks
        return [dg.RunRequest(run_key=f"warehouse-{night}", tags={NIGHTLY_TAG: night})]

    return indicators_after_nightly_ingest
