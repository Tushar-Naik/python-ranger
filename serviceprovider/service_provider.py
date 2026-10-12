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
import threading
from datetime import timedelta
import json
import signal
import time

from kazoo.exceptions import ConnectionClosedError

from common.exceptions import StopRangerUpdate
from serviceprovider.health_check import HealthCheck
from serviceprovider.health_check import _NoHealthCheck
from common.helper import get_default_logger, default_serialize_func, current_milli_time
from common.job import Job
from rangermodels.ranger_models import ClusterDetails, ServiceDetails, HealthcheckStatus, ServiceNode, UNSET_TIMESTAMP
from transport.base import NodeDataSink
from transport.zk import ZkNodeDataSink

'''
This is a ServiceProvider implementation for doing regular ranger updates on a ranger registry.
You may run this in background or run it in foreground by blocking your current thread.

The registry is reached through a NodeDataSink, which defaults to zookeeper. Any other sink
implementation can be handed in instead, the publishing logic stays the same.

Takes care of the following :
- Infinite retry and connection reattempts in case of connection issues
- Proper cleanup of connections to get rid of ephemeral nodes
- Proper logging  
= Does continuous health check pings on a particular health check url if required [optional]

'''

_lock = threading.RLock()


def _acquire_lock():
    """
    Acquire the module-level lock for serializing access to shared data.

    This should be released with _release_lock().
    """
    if _lock:
        _lock.acquire()


def _release_lock():
    """
    Release the module-level lock acquired by calling _acquire_lock().
    """
    if _lock:
        _lock.release()


def _service_shutdown(signum, frame):
    raise StopRangerUpdate


class _RangerClient(object):
    """
    Builds the ServiceNode for every tick and hands it to the configured sink.
    """

    def __init__(self, sink: NodeDataSink, service_details: ServiceDetails, logger):
        self.sink = sink
        self.service_details = service_details
        self.service = service_details.get_service()
        self.logger = logger
        # tracks the instant the node last transitioned into a healthy state, so
        # that healthySinceTimeStamp can be published alongside every update
        self._healthy_since = UNSET_TIMESTAMP

    def start(self):
        self.sink.start()

    def stop(self):
        self.sink.stop()

    def _healthy_since_timestamp(self, status, now):
        if status != HealthcheckStatus.HEALTHY:
            self._healthy_since = UNSET_TIMESTAMP
        elif self._healthy_since == UNSET_TIMESTAMP:
            self._healthy_since = now
        return self._healthy_since

    def build_node(self, status=HealthcheckStatus.HEALTHY):
        now = current_milli_time()
        return ServiceNode(host=self.service_details.host,
                           port=self.service_details.port,
                           node_data=self.service_details.get_node_data(),
                           healthcheck_status=status,
                           last_updated_timestamp=now,
                           routing_weight=self.service_details.routing_weight,
                           healthy_since_timestamp=self._healthy_since_timestamp(status, now),
                           port_scheme=self.service_details.port_scheme)

    def update_tick(self, status=HealthcheckStatus.HEALTHY):
        service_node = self.build_node(status)
        self.logger.debug(f"Updating with: {service_node}")
        return self.sink.update_health(self.service, service_node)


class RangerServiceProvider(object):
    """
    Initialize this class to be able to start and create a Ranger Updater
    """

    def __init__(self, cluster_details: ClusterDetails, service_details: ServiceDetails,
                 health_check: HealthCheck = None, logger=None, node_data_sink: NodeDataSink = None,
                 health_monitors=None):
        """
        :param cluster_details: registry details; the zookeeper connection string is only read
        when the default zookeeper sink is used, the update interval always applies
        :param service_details: Service details like name, host, port etc
        :param health_check: health check url details if any
        :param logger: optional logger
        :param node_data_sink: registry backend to publish to. Defaults to zookeeper, built from
        cluster_details.zk_string
        :param health_monitors: optional list of IsolatedHealthMonitor. The provider is healthy only
        while health_check (if any) reports healthy AND every enabled, non-stale monitor reports
        healthy; a monitor that has gone stale (has not produced a result recently) counts as unhealthy,
        the same as an explicit unhealthy result, since it likely means its thread has died or hung
        """
        self._cluster_details = cluster_details
        self._service_details = service_details
        self.is_running = False
        self._logger = logger if logger is not None else get_default_logger()
        self._health_check = health_check if health_check is not None else _NoHealthCheck(logger)
        self._health_monitors = list(health_monitors) if health_monitors else []
        if node_data_sink is None:
            node_data_sink = ZkNodeDataSink(zk_string=self._cluster_details.zk_string, logger=self._logger)
        self._ranger_client = _RangerClient(node_data_sink, self._service_details, self._logger)
        self._job = None

    def _stop_zk_updates(self):
        if not self.is_running:
            self._logger.info("Already stopped")
            return
        try:
            _acquire_lock()
            if not self.is_running:
                self._logger.info("Already stopped")
                return
            self._logger.info("Stopping all updates to the registry and cleaning up..")
            self._job.stop()
            for monitor in self._health_monitors:
                monitor.stop()
            self._ranger_client.stop()
            self.is_running = False
        finally:
            _release_lock()

    def _block_main_thread(self):
        signal.signal(signal.SIGTERM, _service_shutdown)
        signal.signal(signal.SIGINT, _service_shutdown)
        while True:
            try:
                time.sleep(1)
            except StopRangerUpdate:
                self._stop_zk_updates()
                break

    def _ranger_update_tick(self):
        """
        Perform a single update tick against the registry. Handles error scenarios.
        Does healthcheck if necessary
        """
        try:
            status = self._aggregate_health_status()
            if self._ranger_client.update_tick(status) is None:
                # the sink already logged the cause; re-establish the connection so the
                # next tick has a chance of succeeding
                self._logger.error("Update was not acknowledged by the registry. Re-attempting")
                self._ranger_client.start()
        except ConnectionClosedError:
            self._logger.error("Connection closed. Re-attempting")
            self._ranger_client.start()
        except Exception:
            self._logger.exception("Error while updating the registry")

    def _aggregate_health_status(self):
        """
        :return: HealthcheckStatus.HEALTHY only while health_check (if configured)
        reports healthy and every enabled monitor both reports healthy and has a
        recent result; otherwise HealthcheckStatus.UNHEALTHY
        """
        if not self._health_check.is_healthy():
            return HealthcheckStatus.UNHEALTHY
        for monitor in self._health_monitors:
            if monitor.is_disabled():
                continue
            if not monitor.has_valid_updated_time():
                self._logger.warning(f"Monitor:{monitor.name} has gone stale, treating it as unhealthy")
                return HealthcheckStatus.UNHEALTHY
            if monitor.get_health_status() != HealthcheckStatus.HEALTHY:
                return HealthcheckStatus.UNHEALTHY
        return HealthcheckStatus.HEALTHY

    def start(self, block=False):
        """
        Creates a Thread that updates the registry with service health state updates at regular intervals
        :param block: send block as true if you wish to block the current thread (and wait for an interrupt to stop)
        """
        if self.is_running:
            self._logger.info("Already started")
            return
        try:
            _acquire_lock()
            if self.is_running:
                self._logger.info("Already started")
                return
            self.is_running = True
            self._logger.info(json.dumps(self._cluster_details, default=default_serialize_func))
            self._ranger_client.start()
            for monitor in self._health_monitors:
                monitor.start()
            self._job = Job(timedelta(seconds=self._cluster_details.update_interval_in_secs), self._ranger_update_tick)
        finally:
            _release_lock()

        self._job.daemon = not block
        self._job.start()
        if block:
            self._block_main_thread()

    def stop(self):
        """
        Stop registry updates
        """
        self._stop_zk_updates()
