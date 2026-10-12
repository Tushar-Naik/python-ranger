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
Health monitor framework.

A single URL ping is often not enough to decide whether a service is healthy
-- you may also want to check disk space, an in-rotation flag, queue depth, or
anything else that can be expressed as a periodic check. An
:class:`IsolatedHealthMonitor` runs one such check on its own thread and
interval; a provider can register several of them, and is considered healthy
only while every enabled, non-stale monitor reports healthy.
"""

import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime

from common.helper import get_default_logger
from healthservice.time_entity import TimeEntity
from rangermodels.ranger_models import HealthcheckStatus


class Monitor(ABC):
    @abstractmethod
    def monitor(self):
        """
        :return: the current status, typically a HealthcheckStatus
        """


class IsolatedHealthMonitor(Monitor):
    """
    Runs :meth:`monitor` on its own daemon thread at ``time_entity``'s interval,
    and remembers the most recent result along with when it was produced.
    """

    def __init__(self, name: str, time_entity: TimeEntity, staleness_allowed_in_millis: int = 60000, logger=None):
        """
        :param name: name of this monitor, used in logs
        :param time_entity: how often :meth:`monitor` should be invoked
        :param staleness_allowed_in_millis: if this monitor has not produced a
        result within this many milliseconds, :meth:`has_valid_updated_time`
        reports False -- used to detect a monitor thread that has died or hung
        :param logger: optional logger
        """
        self.name = name
        self.time_entity = time_entity
        self.staleness_allowed_in_millis = staleness_allowed_in_millis
        self.logger = logger if logger is not None else get_default_logger()

        self._health_status = None
        self._last_status_update_time = None
        self._disabled = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def enable(self):
        self._disabled = False

    def disable(self):
        self._disabled = True

    def is_disabled(self):
        return self._disabled

    def get_health_status(self):
        with self._lock:
            return self._health_status

    def has_valid_updated_time(self, current_time: datetime = None):
        current_time = current_time if current_time is not None else datetime.now()
        with self._lock:
            last = self._last_status_update_time
        if last is None:
            return False
        elapsed_ms = (current_time - last).total_seconds() * 1000.0
        return elapsed_ms <= self.staleness_allowed_in_millis

    def _tick(self):
        try:
            status = self.monitor()
        except Exception:
            self.logger.exception(f"Monitor:{self.name} raised while checking health")
            status = HealthcheckStatus.UNHEALTHY
        with self._lock:
            self._health_status = status
            self._last_status_update_time = datetime.now()

    def _run(self):
        if self._stop_event.wait(self.time_entity.initial_delay_seconds()):
            return
        while not self._stop_event.is_set():
            self._tick()
            if self._stop_event.wait(self.time_entity.interval_seconds()):
                return

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f"monitor-{self.name}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @abstractmethod
    def monitor(self):
        """
        :return: HealthcheckStatus for the current check
        """
