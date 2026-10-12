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

import logging
import time
from unittest import mock

import pytest

from healthservice.health_service import HealthService, ServiceHealthAggregator
from healthservice.monitor import IsolatedHealthMonitor, Monitor
from healthservice.monitors.inline import default_healthy_monitor, file_existence_check_monitor
from healthservice.monitors.rotation_status import RotationStatusMonitor
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import ClusterDetails, HealthcheckStatus, ServiceDetails
from serviceprovider.service_provider import RangerServiceProvider

LOGGER = logging.getLogger("test")


def _isolated(status, disabled=False, stale=False, name="isolated"):
    monitor = mock.Mock(spec=IsolatedHealthMonitor)
    monitor.name = name
    monitor.is_disabled.return_value = disabled
    monitor.has_valid_updated_time.return_value = not stale
    monitor.get_health_status.return_value = status
    return monitor


class _StatusMonitor(Monitor):
    """An inline monitor with a scripted result that counts its evaluations."""

    def __init__(self, status, disabled=False):
        self.status = status
        self.disabled = disabled
        self.calls = 0

    def monitor(self):
        self.calls += 1
        return self.status

    def is_disabled(self):
        return self.disabled


def _aggregator():
    return ServiceHealthAggregator(logger=LOGGER)


class TestAggregation:
    def test_is_a_health_service(self):
        assert isinstance(_aggregator(), HealthService)

    def test_no_monitors_is_healthy(self):
        assert _aggregator().get_service_health() == HealthcheckStatus.HEALTHY

    def test_healthy_isolated_monitors_are_healthy(self):
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.HEALTHY))
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.HEALTHY))

        assert aggregator.get_service_health() == HealthcheckStatus.HEALTHY

    def test_one_unhealthy_isolated_monitor_makes_the_service_unhealthy(self):
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.HEALTHY))
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.UNHEALTHY))

        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY

    def test_a_stale_isolated_monitor_is_unhealthy_even_with_a_healthy_last_result(self):
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.HEALTHY, stale=True))

        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY

    def test_a_disabled_isolated_monitor_is_ignored_even_if_unhealthy_and_stale(self):
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.UNHEALTHY, disabled=True, stale=True))

        assert aggregator.get_service_health() == HealthcheckStatus.HEALTHY

    def test_a_monitor_that_has_not_produced_a_result_yet_is_unhealthy(self):
        # nothing to trust before the first tick, which is what has_valid_updated_time reports
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(RotationStatusMonitor("/nonexistent", TimeEntity(100)))

        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY


class TestInlineMonitors:
    def test_a_healthy_inline_monitor_is_healthy(self):
        aggregator = _aggregator()
        aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.HEALTHY))

        assert aggregator.get_service_health() == HealthcheckStatus.HEALTHY

    def test_an_unhealthy_inline_monitor_makes_the_service_unhealthy(self):
        aggregator = _aggregator()
        aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.UNHEALTHY))

        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY

    def test_a_disabled_inline_monitor_is_neither_run_nor_counted(self):
        monitor = _StatusMonitor(HealthcheckStatus.UNHEALTHY, disabled=True)
        aggregator = _aggregator()
        aggregator.add_inline_monitor(monitor)

        assert aggregator.get_service_health() == HealthcheckStatus.HEALTHY
        assert monitor.calls == 0

    def test_inline_monitors_are_evaluated_on_every_request_not_cached(self):
        monitor = _StatusMonitor(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_inline_monitor(monitor)

        aggregator.get_service_health()
        monitor.status = HealthcheckStatus.UNHEALTHY

        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY
        assert monitor.calls == 2

    def test_every_inline_monitor_runs_even_after_one_has_failed(self):
        failing = _StatusMonitor(HealthcheckStatus.UNHEALTHY)
        later = _StatusMonitor(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_inline_monitor(failing)
        aggregator.add_inline_monitor(later)

        aggregator.get_service_health()

        assert later.calls == 1

    def test_isolated_and_inline_monitors_combine(self):
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.HEALTHY))
        aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.UNHEALTHY))

        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY

    def test_inline_monitors_run_without_the_aggregator_being_started(self):
        aggregator = _aggregator()
        aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.UNHEALTHY))

        assert aggregator.is_running() is False
        assert aggregator.get_service_health() == HealthcheckStatus.UNHEALTHY


class TestLifecycle:
    def test_start_starts_every_isolated_monitor(self):
        first, second = _isolated(HealthcheckStatus.HEALTHY), _isolated(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(first)
        aggregator.add_isolated_monitor(second)

        aggregator.start()

        first.start.assert_called_once()
        second.start.assert_called_once()
        assert aggregator.is_running() is True

    def test_start_is_idempotent(self):
        monitor = _isolated(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(monitor)

        aggregator.start()
        aggregator.start()

        monitor.start.assert_called_once()

    def test_stop_stops_every_isolated_monitor(self):
        monitor = _isolated(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(monitor)
        aggregator.start()

        aggregator.stop()

        monitor.stop.assert_called_once()
        assert aggregator.is_running() is False

    def test_stop_when_not_running_is_a_noop(self):
        monitor = _isolated(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(monitor)

        aggregator.stop()

        monitor.stop.assert_not_called()

    def test_can_be_restarted_after_stopping(self):
        monitor = _isolated(HealthcheckStatus.HEALTHY)
        aggregator = _aggregator()
        aggregator.add_isolated_monitor(monitor)
        aggregator.start()
        aggregator.stop()

        aggregator.start()

        assert monitor.start.call_count == 2

    def test_monitors_cannot_be_added_while_running(self):
        aggregator = _aggregator()
        aggregator.start()

        with pytest.raises(RuntimeError):
            aggregator.add_isolated_monitor(_isolated(HealthcheckStatus.HEALTHY))
        with pytest.raises(RuntimeError):
            aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.HEALTHY))

    def test_monitors_can_be_added_again_once_stopped(self):
        aggregator = _aggregator()
        aggregator.start()
        aggregator.stop()

        aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.HEALTHY))


class TestHealthCheckCompatibility:
    def test_is_healthy_mirrors_the_aggregated_health(self):
        aggregator = _aggregator()
        monitor = _StatusMonitor(HealthcheckStatus.HEALTHY)
        aggregator.add_inline_monitor(monitor)
        assert aggregator.is_healthy() is True

        monitor.status = HealthcheckStatus.UNHEALTHY
        assert aggregator.is_healthy() is False

    def test_can_stand_in_as_a_providers_health_check(self):
        sink = mock.Mock()
        sink.update_health.side_effect = lambda service, node: node
        aggregator = _aggregator()
        aggregator.add_inline_monitor(_StatusMonitor(HealthcheckStatus.UNHEALTHY))
        provider = RangerServiceProvider(ClusterDetails("x:2181"),
                                         ServiceDetails("h", 8080, namespace="ns", service_name="svc"),
                                         health_check=aggregator, logger=LOGGER, node_data_sink=sink)

        provider._ranger_update_tick()

        assert sink.update_health.call_args[0][1].healthcheck_status == HealthcheckStatus.UNHEALTHY


class TestMonitorsFactory:
    def test_file_existence_check_monitor(self, tmp_path):
        flag = tmp_path / "in-rotation"
        monitor = file_existence_check_monitor(str(flag))
        assert monitor.monitor() == HealthcheckStatus.UNHEALTHY

        flag.write_text("")
        assert monitor.monitor() == HealthcheckStatus.HEALTHY

        flag.unlink()
        assert monitor.monitor() == HealthcheckStatus.UNHEALTHY

    def test_default_healthy_monitor(self):
        monitor = default_healthy_monitor()
        assert monitor.monitor() == HealthcheckStatus.HEALTHY
        assert monitor.is_disabled() is False

    def test_factory_monitors_are_monitors(self):
        assert isinstance(file_existence_check_monitor("/x"), Monitor)
        assert isinstance(default_healthy_monitor(), Monitor)

    def test_monitor_is_enabled_by_default(self):
        assert _StatusMonitor(HealthcheckStatus.HEALTHY).is_disabled() is False


class TestEndToEnd:
    def test_real_isolated_and_inline_monitors_drive_a_provider(self, tmp_path):
        rotation_file = tmp_path / "rotation"
        rotation_file.write_text("")
        inline_flag = tmp_path / "inline"
        inline_flag.write_text("")

        published = []
        sink = mock.Mock()
        sink.update_health.side_effect = lambda service, node: published.append(node.healthcheck_status) or node

        provider = RangerServiceProvider(
            ClusterDetails("x:2181", update_interval_in_secs=0.05),
            ServiceDetails("h", 8080, namespace="ns", service_name="svc"),
            logger=LOGGER, node_data_sink=sink,
            health_monitors=[RotationStatusMonitor(str(rotation_file), TimeEntity(0.02))],
            inline_health_monitors=[file_existence_check_monitor(str(inline_flag))])
        provider.start()
        try:
            time.sleep(0.4)
            assert published[-1] == HealthcheckStatus.HEALTHY

            inline_flag.unlink()
            time.sleep(0.3)
            assert published[-1] == HealthcheckStatus.UNHEALTHY

            inline_flag.write_text("")
            rotation_file.unlink()
            time.sleep(0.3)
            assert published[-1] == HealthcheckStatus.UNHEALTHY

            rotation_file.write_text("")
            time.sleep(0.3)
            assert published[-1] == HealthcheckStatus.HEALTHY
        finally:
            provider.stop()
