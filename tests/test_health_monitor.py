# Copyright 2022. Tushar Naik
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time
from datetime import datetime, timedelta

import pytest

from healthservice.monitor import IsolatedHealthMonitor
from healthservice.rolling_window import RollingWindowHealthQueue
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import HealthcheckStatus


class _ScriptedMonitor(IsolatedHealthMonitor):
    """A monitor whose check result is controlled by the test."""

    def __init__(self, time_entity, results):
        super().__init__(name="scripted", time_entity=time_entity)
        self._results = list(results)

    def monitor(self):
        return self._results.pop(0) if self._results else HealthcheckStatus.HEALTHY


class _RaisingMonitor(IsolatedHealthMonitor):
    def monitor(self):
        raise RuntimeError("boom")


class TestTimeEntity:
    def test_interval_seconds(self):
        assert TimeEntity(5, time_unit_seconds=2.0).interval_seconds() == 10.0

    def test_default_unit_is_seconds(self):
        assert TimeEntity(3).interval_seconds() == 3.0

    def test_initial_delay_seconds(self):
        assert TimeEntity(1, time_unit_seconds=1.0, initial_delay=5).initial_delay_seconds() == 5.0

    def test_factories(self):
        assert TimeEntity.every_second().interval_seconds() == 1.0
        assert TimeEntity.every_minute().interval_seconds() == 60.0
        assert TimeEntity.every_hour().interval_seconds() == 3600.0
        assert TimeEntity.every_day().interval_seconds() == 86400.0


class TestIsolatedHealthMonitor:
    def test_runs_on_its_own_thread_and_reports_the_result(self):
        monitor = _ScriptedMonitor(TimeEntity(0.02), [HealthcheckStatus.HEALTHY])
        monitor.start()
        try:
            deadline = time.monotonic() + 2
            while monitor.get_health_status() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert monitor.get_health_status() == HealthcheckStatus.HEALTHY
        finally:
            monitor.stop()

    def test_before_the_first_tick_status_is_none_and_not_valid(self):
        monitor = _ScriptedMonitor(TimeEntity(100), [])
        assert monitor.get_health_status() is None
        assert monitor.has_valid_updated_time() is False

    def test_a_raising_check_is_treated_as_unhealthy(self):
        monitor = _RaisingMonitor(name="raising", time_entity=TimeEntity(0.02))
        monitor.start()
        try:
            deadline = time.monotonic() + 2
            while monitor.get_health_status() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert monitor.get_health_status() == HealthcheckStatus.UNHEALTHY
        finally:
            monitor.stop()

    def test_enable_disable(self):
        monitor = _ScriptedMonitor(TimeEntity(100), [])
        assert monitor.is_disabled() is False
        monitor.disable()
        assert monitor.is_disabled() is True
        monitor.enable()
        assert monitor.is_disabled() is False

    def test_stale_result_is_not_valid(self):
        monitor = _ScriptedMonitor(TimeEntity(100), [])
        monitor._health_status = HealthcheckStatus.HEALTHY
        monitor._last_status_update_time = datetime.now() - timedelta(seconds=5)
        monitor.staleness_allowed_in_millis = 1000

        assert monitor.has_valid_updated_time() is False

    def test_fresh_result_is_valid(self):
        monitor = _ScriptedMonitor(TimeEntity(100), [])
        monitor._health_status = HealthcheckStatus.HEALTHY
        monitor._last_status_update_time = datetime.now()
        monitor.staleness_allowed_in_millis = 60000

        assert monitor.has_valid_updated_time() is True

    def test_stop_is_idempotent_and_joins_the_thread(self):
        monitor = _ScriptedMonitor(TimeEntity(100), [])
        monitor.start()
        monitor.stop()
        monitor.stop()  # must not raise


class TestRollingWindowHealthQueue:
    def test_rejects_a_non_positive_window(self):
        with pytest.raises(ValueError):
            RollingWindowHealthQueue(0, 0)

    def test_rejects_more_failures_than_the_window_size(self):
        with pytest.raises(ValueError):
            RollingWindowHealthQueue(3, 4)

    def test_stays_healthy_while_failures_are_within_the_threshold(self):
        queue = RollingWindowHealthQueue(5, 2)
        statuses = [
            queue.check_in_rolling_window(HealthcheckStatus.UNHEALTHY),
            queue.check_in_rolling_window(HealthcheckStatus.UNHEALTHY),
        ]
        assert all(status == HealthcheckStatus.HEALTHY for status in statuses)

    def test_flips_unhealthy_once_the_threshold_is_exceeded(self):
        queue = RollingWindowHealthQueue(5, 1)

        assert queue.check_in_rolling_window(HealthcheckStatus.UNHEALTHY) == HealthcheckStatus.HEALTHY
        assert queue.check_in_rolling_window(HealthcheckStatus.UNHEALTHY) == HealthcheckStatus.UNHEALTHY

    def test_recovers_once_old_failures_roll_out_of_the_window(self):
        queue = RollingWindowHealthQueue(2, 0)

        assert queue.check_in_rolling_window(HealthcheckStatus.UNHEALTHY) == HealthcheckStatus.UNHEALTHY
        assert queue.check_in_rolling_window(HealthcheckStatus.HEALTHY) == HealthcheckStatus.UNHEALTHY
        # the original failure has now rolled out of a window of size 2
        assert queue.check_in_rolling_window(HealthcheckStatus.HEALTHY) == HealthcheckStatus.HEALTHY

    def test_a_single_flaky_failure_does_not_flip_the_status(self):
        queue = RollingWindowHealthQueue(5, 1)
        for _ in range(3):
            assert queue.check_in_rolling_window(HealthcheckStatus.HEALTHY) == HealthcheckStatus.HEALTHY

        assert queue.check_in_rolling_window(HealthcheckStatus.UNHEALTHY) == HealthcheckStatus.HEALTHY

        assert queue.check_in_rolling_window(HealthcheckStatus.HEALTHY) == HealthcheckStatus.HEALTHY
