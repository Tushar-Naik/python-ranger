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

import os
from unittest import mock

from healthservice.monitors.count_monitor import CheckSign, CountMonitor, DiskSpaceMonitor
from healthservice.monitors.ping_check import PingCheckMonitor
from healthservice.monitors.rotation_status import RotationStatusMonitor
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import HealthcheckStatus


class _FixedCountMonitor(CountMonitor):
    def __init__(self, count, check_sign, threshold):
        super().__init__(name="fixed", check_sign=check_sign, threshold=threshold, time_entity=TimeEntity(100))
        self._count = count

    def get_count(self):
        return self._count


class TestRotationStatusMonitor:
    def test_healthy_when_the_file_exists(self, tmp_path):
        rotation_file = tmp_path / "rotation"
        rotation_file.write_text("in")

        monitor = RotationStatusMonitor(str(rotation_file))

        assert monitor.monitor() == HealthcheckStatus.HEALTHY

    def test_unhealthy_when_the_file_is_absent(self, tmp_path):
        monitor = RotationStatusMonitor(str(tmp_path / "does-not-exist"))

        assert monitor.monitor() == HealthcheckStatus.UNHEALTHY

    def test_flips_once_the_file_is_removed(self, tmp_path):
        rotation_file = tmp_path / "rotation"
        rotation_file.write_text("in")
        monitor = RotationStatusMonitor(str(rotation_file))
        assert monitor.monitor() == HealthcheckStatus.HEALTHY

        os.remove(rotation_file)

        assert monitor.monitor() == HealthcheckStatus.UNHEALTHY

    def test_defaults_to_checking_every_second(self):
        monitor = RotationStatusMonitor("/tmp/whatever")
        assert monitor.time_entity.interval_seconds() == 1.0


class TestCountMonitor:
    def test_lesser_than(self):
        assert _FixedCountMonitor(5, CheckSign.LESSER_THAN, 10).monitor() == HealthcheckStatus.HEALTHY
        assert _FixedCountMonitor(10, CheckSign.LESSER_THAN, 10).monitor() == HealthcheckStatus.UNHEALTHY

    def test_lesser_than_equalto(self):
        assert _FixedCountMonitor(10, CheckSign.LESSER_THAN_EQUALTO, 10).monitor() == HealthcheckStatus.HEALTHY
        assert _FixedCountMonitor(11, CheckSign.LESSER_THAN_EQUALTO, 10).monitor() == HealthcheckStatus.UNHEALTHY

    def test_greater_than(self):
        assert _FixedCountMonitor(11, CheckSign.GREATER_THAN, 10).monitor() == HealthcheckStatus.HEALTHY
        assert _FixedCountMonitor(10, CheckSign.GREATER_THAN, 10).monitor() == HealthcheckStatus.UNHEALTHY

    def test_greater_than_equalto(self):
        assert _FixedCountMonitor(10, CheckSign.GREATER_THAN_EQUALTO, 10).monitor() == HealthcheckStatus.HEALTHY
        assert _FixedCountMonitor(9, CheckSign.GREATER_THAN_EQUALTO, 10).monitor() == HealthcheckStatus.UNHEALTHY


class TestDiskSpaceMonitor:
    def test_healthy_when_enough_free_space(self, tmp_path):
        monitor = DiskSpaceMonitor(str(tmp_path), threshold_bytes=1, time_entity=TimeEntity(100))

        assert monitor.monitor() == HealthcheckStatus.HEALTHY

    def test_unhealthy_when_below_the_threshold(self, tmp_path):
        monitor = DiskSpaceMonitor(str(tmp_path), threshold_bytes=1, time_entity=TimeEntity(100))

        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=0)):
            assert monitor.monitor() == HealthcheckStatus.UNHEALTHY


class TestPingCheckMonitor:
    def _response(self, status_code):
        response = mock.Mock()
        response.status_code = status_code
        return response

    def test_healthy_on_200(self):
        monitor = PingCheckMonitor(TimeEntity(100), url="http://h/health", ping_window_size=1, max_failures=0)
        with mock.patch("requests.request", return_value=self._response(200)):
            assert monitor.monitor() == HealthcheckStatus.HEALTHY

    def test_unhealthy_on_non_200(self):
        monitor = PingCheckMonitor(TimeEntity(100), url="http://h/health", ping_window_size=1, max_failures=0)
        with mock.patch("requests.request", return_value=self._response(500)):
            assert monitor.monitor() == HealthcheckStatus.UNHEALTHY

    def test_unhealthy_on_connection_error(self):
        monitor = PingCheckMonitor(TimeEntity(100), url="http://h/health", ping_window_size=1, max_failures=0)
        with mock.patch("requests.request", side_effect=ConnectionError("boom")):
            assert monitor.monitor() == HealthcheckStatus.UNHEALTHY

    def test_a_single_flaky_ping_does_not_flip_the_status(self):
        monitor = PingCheckMonitor(TimeEntity(100), url="http://h/health", ping_window_size=5, max_failures=1)
        responses = [self._response(200), self._response(200), self._response(500), self._response(200)]
        with mock.patch("requests.request", side_effect=responses):
            results = [monitor.monitor() for _ in responses]

        assert results == [HealthcheckStatus.HEALTHY] * 4

    def test_method_and_headers_are_forwarded(self):
        monitor = PingCheckMonitor(TimeEntity(100), url="http://h/health", method="POST",
                                   headers={"X": "Y"}, ping_window_size=1, max_failures=0)
        with mock.patch("requests.request", return_value=self._response(200)) as request:
            monitor.monitor()

        assert request.call_args.args[0] == "POST"
        assert request.call_args.kwargs["headers"] == {"X": "Y"}
