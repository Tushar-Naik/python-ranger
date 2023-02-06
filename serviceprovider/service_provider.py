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
from kazoo.retry import KazooRetry
from kazoo.client import KazooClient

from common.exceptions import StopRangerUpdate
from serviceprovider.health_check import HealthCheck
from serviceprovider.health_check import _NoHealthCheck
from common.helper import get_default_logger, default_serialize_func, current_milli_time
from common.job import Job
from rangermodels.ranger_models import ClusterDetails, ServiceDetails, HealthcheckStatus, NodeData, ServiceNode

'''
This is a ServiceProvider implementation for doing regular ranger updates on zookeeper
You may run this in background or run it in foreground by blocking your current thread.

Takes care of the following :
- Infinite retry and connection reattempts in case of zk connection issues 
- Proper cleanup of zk connections to get rid of ephemeral nodes
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
    An internal client for all the zk talks, with the ranger logic
    """
    def __init__(self, zk: KazooClient, cluster_details: ClusterDetails, service_details: ServiceDetails, logger):
        self.zk = zk
        self.cluster_details = cluster_details
        self.service_details = service_details
        self.logger = logger

    def start(self):
        if not self.zk.connected:
            self.zk.start()

    def stop(self):
        self.zk.stop()

    def update_tick(self, status=HealthcheckStatus.HEALTHY):
        node_data = NodeData(self.service_details.environment, self.service_details.region, self.service_details.tags)
        service_node = ServiceNode(self.service_details.host, self.service_details.port, node_data,
                                   status, current_milli_time())
        data_bytes = str.encode(json.dumps(service_node.to_dict()))
        self.logger.info(f"Updating with: {str(data_bytes)}")
        if self.zk.exists(self.service_details.get_path()):
            self.zk.set(self.service_details.get_path(), data_bytes)
        else:
            # ensure that you create only ephemeral nodes
            self.zk.ensure_path(self.service_details.get_root_path())
            self.zk.create(self.service_details.get_path(), data_bytes, ephemeral=True)


class RangerServiceProvider(object):
    """
    Initialize this class to be able to start and create a Ranger Updater
    """

    def __init__(self, cluster_details: ClusterDetails, service_details: ServiceDetails,
                 health_check: HealthCheck = None, logger=None):
        """
        :param cluster_details: Zookeeper cluster details
        :param service_details: Service details like name, host, port etc
        :param health_check: health check url details if any
        :param logger: optional logger
        """
        self._cluster_details = cluster_details
        self._service_details = service_details
        self.is_running = False
        self._logger = logger if logger is not None else get_default_logger()
        self._health_check = health_check if health_check is not None else _NoHealthCheck(logger)
        self._ranger_client = _RangerClient(
            KazooClient(hosts=self._cluster_details.zk_string,
                        # proper infinite retries to ensure we handle network flakiness
                        connection_retry=KazooRetry(max_tries=float('inf'), delay=1, max_delay=5)),
            self._cluster_details,
            self._service_details,
            self._logger)
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
            self._logger.info("Stopping all updates to zk and cleaning up..")
            self._job.stop()
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
        Used to perform a single tick update to zookeeper. Handles error scenarios. Does healthcheck if necessary
        """
        try:
            if self._health_check.is_healthy():
                self._ranger_client.update_tick(HealthcheckStatus.HEALTHY)
            else:
                self._ranger_client.update_tick(HealthcheckStatus.UNHEALTHY)
        except ConnectionClosedError:
            self._logger.error("Connection closed. Re-attempting")
            self._ranger_client.start()
        except Exception:
            self._logger.exception("Error while updating zk")

    def start(self, block=False):
        """
        Creates a Thread that updates zookeeper with service health state updates at regular intervals
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
            self._job = Job(timedelta(seconds=self._cluster_details.update_interval_in_secs), self._ranger_update_tick)
        finally:
            _release_lock()

        self._job.daemon = not block
        self._job.start()
        if block:
            self._block_main_thread()

    def stop(self):
        """
        Stop zookeeper updates
        """
        self._stop_zk_updates()
