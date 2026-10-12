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
A reusable health aggregator.

Combines any number of monitors into a single service health:

* **isolated monitors** (:class:`~healthservice.monitor.IsolatedHealthMonitor`) run
  on their own thread at their own interval and are only *read* when health is
  asked for. A monitor that reports unhealthy, or that has gone stale (its thread
  died or hung, so its last result can no longer be trusted), makes the service
  unhealthy.
* **inline monitors** (plain :class:`~healthservice.monitor.Monitor`) have no
  thread of their own. They are executed synchronously, on the caller's thread,
  every time health is asked for, which suits checks that are cheap enough to
  evaluate on demand (a file existing, a flag being set).

Disabled monitors of either kind are skipped. This mirrors ``HealthService`` /
``ServiceHealthAggregator`` of the reference implementation (``appform-io/ranger``).
"""

import threading
from abc import ABC, abstractmethod

from common.helper import get_default_logger
from healthservice.monitor import IsolatedHealthMonitor, Monitor
from rangermodels.ranger_models import HealthcheckStatus


class HealthService(ABC):
    """
    Tracks the health of a service from a set of monitors.
    """

    @abstractmethod
    def add_isolated_monitor(self, monitor: IsolatedHealthMonitor):
        """
        Register a monitor that is scheduled on its own thread.
        """

    @abstractmethod
    def add_inline_monitor(self, monitor: Monitor):
        """
        Register a monitor that is evaluated inline, on the caller's thread, whenever
        health is requested.
        """

    @abstractmethod
    def start(self):
        """
        Start every registered isolated monitor.
        """

    @abstractmethod
    def stop(self):
        """
        Stop every registered isolated monitor.
        """

    @abstractmethod
    def get_service_health(self):
        """
        :return: the aggregated health of the service
        """


class ServiceHealthAggregator(HealthService):
    """
    Aggregates isolated and inline monitors into a single HealthcheckStatus.

    Monitors can only be registered while the aggregator is not running.
    """

    def __init__(self, logger=None):
        self._logger = logger if logger is not None else get_default_logger()
        self._isolated_monitors = []
        self._inline_monitors = []
        self._running = False
        self._lock = threading.RLock()

    def is_running(self):
        return self._running

    def add_isolated_monitor(self, monitor: IsolatedHealthMonitor):
        with self._lock:
            if self._running:
                raise RuntimeError("Cannot add a monitor when the aggregator is running")
            self._isolated_monitors.append(monitor)

    def add_inline_monitor(self, monitor: Monitor):
        with self._lock:
            if self._running:
                raise RuntimeError("Cannot add a monitor when the aggregator is running")
            self._inline_monitors.append(monitor)

    def start(self):
        with self._lock:
            if self._running:
                self._logger.info("Service health aggregator is already running")
                return
            for monitor in self._isolated_monitors:
                monitor.start()
            self._running = True

    def stop(self):
        with self._lock:
            if not self._running:
                self._logger.info("Service health aggregator is not running, nothing to stop")
                return
            for monitor in self._isolated_monitors:
                monitor.stop()
            self._running = False

    def _is_isolated_monitor_unhealthy(self, monitor):
        if monitor.get_health_status() == HealthcheckStatus.UNHEALTHY:
            return True
        if not monitor.has_valid_updated_time():
            # a monitor that stopped producing results is as untrustworthy as one reporting unhealthy
            self._logger.warning(f"Monitor:{monitor.name} is stuck and its status is stale. "
                                 f"Marking service as unhealthy")
            return True
        return False

    def get_service_health(self):
        with self._lock:
            isolated_monitors = list(self._isolated_monitors)
            inline_monitors = list(self._inline_monitors)

        healthy = True
        for monitor in isolated_monitors:
            if monitor.is_disabled():
                continue
            if self._is_isolated_monitor_unhealthy(monitor):
                healthy = False

        # every inline monitor is evaluated even once one has failed, so that each
        # gets its turn to log and update whatever state it keeps
        for monitor in inline_monitors:
            if monitor.is_disabled():
                continue
            if monitor.monitor() == HealthcheckStatus.UNHEALTHY:
                healthy = False

        return HealthcheckStatus.HEALTHY if healthy else HealthcheckStatus.UNHEALTHY

    def is_healthy(self):
        """
        Lets an aggregator stand in anywhere a ``HealthCheck`` is expected, such as
        the ``health_check`` argument of a service provider.

        :return: True when the aggregated health is healthy
        """
        return self.get_service_health() == HealthcheckStatus.HEALTHY
