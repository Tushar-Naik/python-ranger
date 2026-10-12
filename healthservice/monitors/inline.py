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
Ready-made inline monitors, for one-off checks that do not warrant a subclass.
Register them with :meth:`~healthservice.health_service.ServiceHealthAggregator.add_inline_monitor`.
"""

import os

from healthservice.monitor import Monitor
from rangermodels.ranger_models import HealthcheckStatus


class _CallableMonitor(Monitor):
    def __init__(self, check):
        self._check = check

    def monitor(self):
        return self._check()


def file_existence_check_monitor(file_path: str) -> Monitor:
    """
    :param file_path: path to look for on every evaluation
    :return: an inline monitor that is healthy exactly while the file exists
    """
    return _CallableMonitor(
        lambda: HealthcheckStatus.HEALTHY if os.path.exists(file_path) else HealthcheckStatus.UNHEALTHY)


def default_healthy_monitor() -> Monitor:
    """
    :return: an inline monitor that is always healthy; a placeholder for a service
    that has nothing of its own to check
    """
    return _CallableMonitor(lambda: HealthcheckStatus.HEALTHY)
