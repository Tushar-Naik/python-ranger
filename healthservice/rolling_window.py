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
Flap damping for a noisy underlying check.

A single flaky failure (one dropped ping, one slow disk read) should not flip
a node's published health back and forth. This keeps a fixed-size sliding
window of the most recent raw results and only reports unhealthy once the
number of unhealthy results currently in that window exceeds a threshold.
"""

from collections import deque

from rangermodels.ranger_models import HealthcheckStatus


class RollingWindowHealthQueue(object):
    def __init__(self, rolling_window_size: int, max_failures: int):
        """
        :param rolling_window_size: number of most recent results to consider
        :param max_failures: the window is reported unhealthy once more than
        this many of its entries are unhealthy
        """
        if rolling_window_size <= 0:
            raise ValueError("rolling_window_size can't be <= 0")
        if max_failures > rolling_window_size:
            raise ValueError("max_failures can't be greater than the rolling_window_size")
        self._window = deque(maxlen=rolling_window_size)
        self._max_failures = max_failures

    def check_in_rolling_window(self, current_health_status: HealthcheckStatus):
        """
        Records the latest raw result and returns the damped status.

        :param current_health_status: the latest, undamped check result
        :return: HealthcheckStatus.HEALTHY if the window currently holds at
        most max_failures unhealthy entries, HealthcheckStatus.UNHEALTHY otherwise
        """
        self._window.append(current_health_status)
        failures = sum(1 for status in self._window if status == HealthcheckStatus.UNHEALTHY)
        return HealthcheckStatus.UNHEALTHY if failures > self._max_failures else HealthcheckStatus.HEALTHY
