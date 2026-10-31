from datetime import date, datetime

from custom_components.cortex import tariff as t

PLAN = t.Plan()


def at(day, hour):
    return datetime(2026, 11, day, hour)  # Nov 2 2026 is a Monday


def test_periods_business_day():
    assert t.period(at(2, 11), PLAN) == t.SHOULDER
    assert t.period(at(2, 17), PLAN) == t.PEAK
    assert t.period(at(2, 15), PLAN) == t.OFF_PEAK
    assert t.period(at(2, 22), PLAN) == t.OFF_PEAK


def test_weekend_and_holiday_have_no_peak():
    assert t.period(at(1, 17), PLAN) == t.OFF_PEAK  # Sunday
    assert t.period(at(1, 11), PLAN) == t.SHOULDER  # shoulder still applies
    assert t.period(at(2, 17), PLAN, is_holiday=True) == t.OFF_PEAK


def test_rates_and_season():
    assert t.import_rate(at(2, 17), PLAN) == 41.91  # high season
    assert t.import_rate(datetime(2026, 6, 1, 17), PLAN) == 42.416  # low season
    assert t.import_rate(at(2, 11), PLAN) == 11.11
    assert t.feed_in_rate(at(2, 18), PLAN) == 28.0
    assert t.feed_in_rate(at(2, 7), PLAN) == 3.0


def test_next_change():
    when, to = t.next_change(at(2, 11), PLAN)
    assert (when.hour, to) == (14, t.OFF_PEAK)
    when, to = t.next_change(at(2, 15), PLAN)
    assert (when.hour, to) == (16, t.PEAK)
    # Friday evening: next change is Saturday morning's... shoulder at 10:00
    when, to = t.next_change(datetime(2026, 11, 6, 20), PLAN)
    assert to == t.SHOULDER and when.day == 7 and when.hour == 10


def test_export_cover():
    assert t.export_kwh_to_cover(PLAN) == 5.95


def test_shortfall_and_storage():
    assert t.pv_shortfall(42.2, 54, 50) == -19.2  # 23 kWh room - 42.2 forecast
    assert t.pv_shortfall(10, 50, 50, True, 40, 80, 82.5) == 48.0  # 25 + 33 - 10
    assert t.stored_kwh(54, 50) == 27.0
    assert t.usable_kwh(54, 50) == 17.0
    assert t.room_kwh(54, 50) == 23.0
    assert t.solar_day(25, 30) == "low" and t.solar_day(42, 30) == "ok"


def test_schedule_rows():
    rows = t.schedule(date(2026, 11, 2), PLAN)
    assert len(rows) == 24 and rows[11][1] == 11.11 and rows[18][2] == 28.0
