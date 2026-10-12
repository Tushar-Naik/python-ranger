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

"""
A monitor that pings an HTTP endpoint at a regular interval, with the result
damped through a :class:`~healthservice.rolling_window.RollingWindowHealthQueue`
so a single flaky ping does not flip the published health.
"""

import requests

from healthservice.monitor import IsolatedHealthMonitor
from healthservice.rolling_window import RollingWindowHealthQueue
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import HealthcheckStatus


class PingCheckMonitor(IsolatedHealthMonitor):
    def __init__(self,
                 time_entity: TimeEntity,
                 url: str,
                 ping_timeout_in_seconds: float = 1.0,
                 ping_window_size: int = 5,
                 max_failures: int = 3,
                 method: str = 'GET',
                 headers=None,
                 staleness_allowed_in_millis: int = 60000,
                 logger=None):
        """
        :param time_entity: how often to ping
        :param url: url to ping
        :param ping_timeout_in_seconds: timeout for a single ping
        :param ping_window_size: rolling window size for flap damping
        :param max_failures: failures allowed within that window before reporting unhealthy
        :param method: HTTP method to use for the ping
        :param headers: optional headers for the ping request
        """
        super().__init__(name=self.__class__.__name__, time_entity=time_entity,
                         staleness_allowed_in_millis=staleness_allowed_in_millis, logger=logger)
        self.url = url
        self.method = method
        self.headers = headers
        self.ping_timeout_in_seconds = ping_timeout_in_seconds
        self._rolling_window = RollingWindowHealthQueue(ping_window_size, max_failures)

    def _ping(self):
        try:
            response = requests.request(self.method, self.url, headers=self.headers,
                                        timeout=self.ping_timeout_in_seconds)
            return response.status_code == 200
        except Exception:
            self.logger.warning(f"{self.name}: ping failed for url:{self.url}")
            return False

    def monitor(self):
        raw_status = HealthcheckStatus.HEALTHY if self._ping() else HealthcheckStatus.UNHEALTHY
        return self._rolling_window.check_in_rolling_window(raw_status)
