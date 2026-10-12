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
Dynamic, multi-service discovery.

:class:`~servicefinder.service_finder.RangerServiceFinder` requires every
service name to be known up front. A :class:`ServiceFinderHub` instead asks
the registry "what services currently exist" on a timer, and builds or tears
down a :class:`~servicefinder.simple_finder.SimpleServiceFinder` for each one
automatically, so a consumer never has to hardcode the full set of services it
might ever want to call, and picks up newly registered services without a restart.
"""

import threading
from datetime import timedelta

from common.helper import get_default_logger
from common.job import Job
from transport.base import NodeDataSource

DEFAULT_REFRESH_INTERVAL_MS = 10000


class ServiceFinderHub(object):
    """
    Owns one finder per discovered service, refreshing the service catalogue
    and every finder's node view on an interval.
    """

    def __init__(self,
                 source: NodeDataSource,
                 finder_factory,
                 excluded_services=None,
                 refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS,
                 logger=None):
        """
        :param source: registry backend; its ``services()`` drives discovery and
        its ``nodes()`` feeds each per-service finder
        :param finder_factory: ``callable(Service) -> SimpleServiceFinder``, used to
        build a finder the first time a service is seen
        :param excluded_services: service names to never build a finder for, even
        if the source reports them
        :param refresh_interval_ms: how often to re-poll the service catalogue
        and every known finder
        :param logger: optional logger
        """
        self._source = source
        self._finder_factory = finder_factory
        self._excluded_services = set(excluded_services) if excluded_services else set()
        self._refresh_interval_ms = refresh_interval_ms
        self._logger = logger if logger is not None else get_default_logger()

        self._finders = {}
        self._lock = threading.Lock()
        self._job = None
        self._ready = threading.Event()
        self._update_listeners = []
        self.is_running = False

    def register_update_listener(self, listener):
        """
        :param listener: ``callable()`` invoked, best effort, after every refresh
        """
        self._update_listeners.append(listener)

    def _eligible(self, services):
        return {service for service in services if service.service_name not in self._excluded_services}

    def _refresh_once(self):
        try:
            self._do_refresh()
        finally:
            # mark that at least one refresh attempt has completed, successful or
            # not, so start() never blocks waiting for an attempt that already
            # happened and failed
            self._ready.set()

    def _do_refresh(self):
        try:
            services = self._eligible(self._source.services())
        except Exception:
            self._logger.exception("Error while listing services from the registry")
            return

        with self._lock:
            current = set(self._finders.keys())
            for service in services - current:
                try:
                    finder = self._finder_factory(service)
                    finder.refresh()
                    self._finders[service] = finder
                    self._logger.info(f"Discovered new service:{service.name()}")
                except Exception:
                    self._logger.exception(f"Error while building a finder for service:{service.name()}")
            for service in current - services:
                self._logger.info(f"Service no longer present, dropping its finder:{service.name()}")
                del self._finders[service]
            finders = list(self._finders.values())

        for finder in finders:
            try:
                finder.refresh()
            except Exception:
                self._logger.exception(f"Error while refreshing service:{finder.service.name()}")

        for listener in self._update_listeners:
            try:
                listener()
            except Exception:
                self._logger.exception("Error in a hub update listener")

    def start(self):
        """
        Performs an initial, synchronous refresh attempt and starts the
        background polling job. Returns as soon as that attempt completes,
        whether it succeeded or not; a registry that is down at startup does
        not block the caller, it just leaves the hub with no known services
        until the background job's next tick succeeds.
        """
        if self.is_running:
            self._logger.info("Already started")
            return
        self.is_running = True
        self._source.start()
        self._refresh_once()
        self._job = Job(timedelta(milliseconds=self._refresh_interval_ms), self._refresh_once)
        self._job.daemon = True
        self._job.start()

    def stop(self):
        if not self.is_running:
            return
        if self._job is not None:
            self._job.stop()
        self._source.stop()
        self.is_running = False

    def services(self):
        """
        :return: the set of services currently known to the hub
        """
        with self._lock:
            return set(self._finders.keys())

    def finder(self, service):
        """
        :param service: the Service to look up
        :return: its SimpleServiceFinder, or None if not currently known
        """
        with self._lock:
            return self._finders.get(service)

    def is_ready(self):
        """
        :return: True once at least one refresh attempt has completed, whether
        it succeeded or not
        """
        return self._ready.is_set()
