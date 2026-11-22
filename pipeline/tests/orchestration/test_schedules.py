"""Tests for the nightly run: stage and load every project at 02:00 Nairobi
time, then rebuild the indicators once, after every project's run has finished.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from janice_pipeline.orchestration.schedules import (
    NIGHTLY_TAG,
    build_indicators_sensor,
    build_nightly_schedule,
    nightly_runs_finished,
)
from janice_pipeline.projects.registry import Project

NAIROBI = ZoneInfo("Africa/Nairobi")
PROJECTS = [
    Project(key="neonatal", site_field="hosp_id"),
    Project(key="paediatrics", site_field="hosp_id"),
    Project(key="maternity", site_field="hosp_id"),
]
NIGHT = datetime(2026, 11, 23, 2, 0, tzinfo=NAIROBI)


def test_the_nightly_schedule_starts_one_run_per_project():
    schedule = build_nightly_schedule(PROJECTS, running=False)

    requests = list(schedule(dg.build_schedule_context(scheduled_execution_time=NIGHT)))

    assert [r.partition_key for r in requests] == ["neonatal", "paediatrics", "maternity"]
    assert all(r.tags[NIGHTLY_TAG] == "2026-11-23" for r in requests)
    # One run per project per night, even if the scheduler ticks twice
    assert requests[0].run_key == "2026-11-23-neonatal"


def test_the_schedule_runs_at_two_in_the_morning_nairobi_time():
    schedule = build_nightly_schedule(PROJECTS, running=False)

    assert schedule.cron_schedule == "0 2 * * *"
    assert schedule.execution_timezone == "Africa/Nairobi"


def test_schedules_are_off_unless_turned_on():
    # A laptop must never start nightly runs by itself
    assert build_nightly_schedule(PROJECTS, running=False).default_status == (
        dg.DefaultScheduleStatus.STOPPED
    )
    assert build_nightly_schedule(PROJECTS, running=True).default_status == (
        dg.DefaultScheduleStatus.RUNNING
    )


SUCCESS = dg.DagsterRunStatus.SUCCESS
FAILURE = dg.DagsterRunStatus.FAILURE
STARTED = dg.DagsterRunStatus.STARTED


def test_indicators_wait_until_every_project_has_finished():
    assert not nightly_runs_finished([], expected=3)
    assert not nightly_runs_finished([SUCCESS, SUCCESS], expected=3)
    assert not nightly_runs_finished([SUCCESS, SUCCESS, STARTED], expected=3)
    assert nightly_runs_finished([SUCCESS, SUCCESS, SUCCESS], expected=3)


def test_a_failed_project_does_not_hold_back_the_others():
    # A failed load leaves that project's previous rows in place, so the
    # indicators can still be rebuilt for everyone
    assert nightly_runs_finished([SUCCESS, FAILURE, SUCCESS], expected=3)


@dg.op
def ok():
    pass


@dg.job
def fake_ingest():
    ok()


def run_fake_ingest(instance, tags):
    fake_ingest.execute_in_process(instance=instance, tags=tags)


def test_the_sensor_requests_one_indicator_build_per_night():
    sensor = build_indicators_sensor(PROJECTS, running=False, now=lambda: NIGHT)
    with dg.instance_for_test() as instance:
        for _ in PROJECTS:
            run_fake_ingest(instance, {NIGHTLY_TAG: "2026-11-23"})

        result = sensor(dg.build_sensor_context(instance=instance))

    (request,) = list(result)
    assert request.run_key == "warehouse-2026-11-23"


def test_the_sensor_skips_while_projects_are_still_loading():
    sensor = build_indicators_sensor(PROJECTS, running=False, now=lambda: NIGHT)
    with dg.instance_for_test() as instance:
        run_fake_ingest(instance, {NIGHTLY_TAG: "2026-11-23"})

        result = sensor(dg.build_sensor_context(instance=instance))

    assert isinstance(result, dg.SkipReason)
    assert "1 of 3" in result.skip_message
