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
A simple in/out of rotation check: a service is healthy exactly while a file
exists at a known path. Removing the file (e.g. during a controlled drain) is
enough to mark the node unhealthy without touching any other check.
"""

import os

from healthservice.monitor import IsolatedHealthMonitor
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import HealthcheckStatus


class RotationStatusMonitor(IsolatedHealthMonitor):
    def __init__(self, file_path: str, time_entity: TimeEntity = None, staleness_allowed_in_millis: int = 60000,
                 logger=None):
        """
        :param file_path: path checked for existence on every tick
        :param time_entity: how often to check, defaults to every second
        """
        super().__init__(name=self.__class__.__name__,
                         time_entity=time_entity if time_entity is not None else TimeEntity.every_second(),
                         staleness_allowed_in_millis=staleness_allowed_in_millis, logger=logger)
        self.file_path = file_path

    def monitor(self):
        return HealthcheckStatus.HEALTHY if os.path.exists(self.file_path) else HealthcheckStatus.UNHEALTHY
