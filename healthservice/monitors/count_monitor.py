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
A monitor that marks a service unhealthy once some countable quantity breaches
a threshold -- queue depth, open file descriptors, active thread count,
anything :meth:`get_count` can report. Subclass and implement :meth:`get_count`.
"""

from abc import abstractmethod
from enum import Enum

import shutil

from healthservice.monitor import IsolatedHealthMonitor
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import HealthcheckStatus


class CheckSign(Enum):
    LESSER_THAN = 'lesser_than'
    LESSER_THAN_EQUALTO = 'lesser_than_equalto'
    GREATER_THAN = 'greater_than'
    GREATER_THAN_EQUALTO = 'greater_than_equalto'


class CountMonitor(IsolatedHealthMonitor):
    def __init__(self, name: str, check_sign: CheckSign, threshold, time_entity: TimeEntity,
                 staleness_allowed_in_millis: int = 60000, logger=None):
        """
        :param name: name of this monitor, used in logs
        :param check_sign: comparison applied between the current count and threshold
        :param threshold: the healthy/unhealthy boundary
        :param time_entity: how often to check
        """
        super().__init__(name=name, time_entity=time_entity,
                         staleness_allowed_in_millis=staleness_allowed_in_millis, logger=logger)
        self.check_sign = check_sign
        self.threshold = threshold

    @abstractmethod
    def get_count(self):
        """
        :return: the current value of whatever this monitor is tracking
        """

    def monitor(self):
        count = self.get_count()
        comparisons = {
            CheckSign.LESSER_THAN: count < self.threshold,
            CheckSign.LESSER_THAN_EQUALTO: count <= self.threshold,
            CheckSign.GREATER_THAN: count > self.threshold,
            CheckSign.GREATER_THAN_EQUALTO: count >= self.threshold,
        }
        return HealthcheckStatus.HEALTHY if comparisons[self.check_sign] else HealthcheckStatus.UNHEALTHY


class DiskSpaceMonitor(CountMonitor):
    """
    A worked example: marks the service unhealthy once free disk space at
    ``path`` drops below ``threshold_bytes``.
    """

    def __init__(self, path: str, threshold_bytes: int, time_entity: TimeEntity,
                 staleness_allowed_in_millis: int = 60000, logger=None):
        super().__init__(name=self.__class__.__name__, check_sign=CheckSign.GREATER_THAN_EQUALTO,
                         threshold=threshold_bytes, time_entity=time_entity,
                         staleness_allowed_in_millis=staleness_allowed_in_millis, logger=logger)
        self.path = path

    def get_count(self):
        return shutil.disk_usage(self.path).free
