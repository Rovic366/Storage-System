"""Maintenance service rules."""

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from maintenance import services
from maintenance.models import MaintenanceLog, MaintenanceSchedule

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user():
    return User.objects.create_user("tech", "tech@x.example", "pw-123456")


def test_log_task_rolls_next_due(make_tool):
    schedule = MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="calibration", interval_days=90,
        next_due=timezone.localdate())
    log, refreshed = services.log_task(
        schedule, _user(), date=timezone.localdate(), cost=25, notes="OK")
    assert log.schedule == schedule
    assert refreshed.last_done == timezone.localdate()
    assert refreshed.next_due == timezone.localdate() + dt.timedelta(days=90)
    assert MaintenanceLog.objects.filter(pk=log.pk).exists()


def test_log_task_future_date_rejected(make_tool):
    schedule = MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="inspection", interval_days=30,
        next_due=timezone.localdate())
    future = timezone.localdate() + dt.timedelta(days=2)
    with pytest.raises((services.StockError, ValueError)):
        services.log_task(schedule, _user(), date=future)


def test_schedule_overdue_count(make_tool):
    overdue = MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="calibration", interval_days=60,
        next_due=timezone.localdate() - dt.timedelta(days=3))
    upcoming = MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="service", interval_days=30,
        next_due=timezone.localdate() + dt.timedelta(days=1))
    from maintenance.models import MaintenanceSchedule as MS

    qs = MS.objects.overdue()
    assert qs.filter(pk=overdue.pk).exists()
    assert not qs.filter(pk=upcoming.pk).exists()
    due7 = MS.objects.due_within(7)
    assert due7.filter(pk=upcoming.pk).exists()


def test_validate_schedule_dates_window(make_tool):
    schedule = MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="repair", interval_days=90,
        next_due=timezone.localdate() + dt.timedelta(days=90))
    assert schedule.pk


@pytest.mark.parametrize("task_type", ["calibration", "inspection", "repair", "service"])
def test_unique_schedule_per_tool_task(make_tool, task_type):
    tool = make_tool()
    MaintenanceSchedule.objects.create(
        tool=tool, task_type=task_type, interval_days=30,
        next_due=timezone.localdate())
    with pytest.raises(Exception):
        MaintenanceSchedule.objects.create(
            tool=tool, task_type=task_type, interval_days=30,
            next_due=timezone.localdate())
