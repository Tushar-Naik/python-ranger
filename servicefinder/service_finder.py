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

import json
import threading
from datetime import timedelta

from kazoo.client import KazooClient
from kazoo.exceptions import NoNodeError
from kazoo.retry import KazooRetry

from common.exceptions import RangerFinderNotStartedException
from common.job import Job
from rangermodels.ranger_models import ClusterDetails, ServiceNode, HealthcheckStatus
from common.helper import get_default_logger, current_milli_time, default_serialize_func
from servicefinder.criteria import Criteria
from servicefinder.node_selector import Selector, RandomNodeSelector

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


class _RangerClient(object):
    """
    An internal client class used to implement all the zk talks
    """
    def __init__(self, zk: KazooClient, path, services, logger):
        self.zk = zk
        self.path = path
        self.services = services
        self.logger = logger

    def start(self):
        self.zk.start()

    def stop(self):
        self.zk.stop()

    def get_nodes(self):
        self.logger.debug(f"Fetching updates from zk for {self.services}")
        service_nodes = {}
        for service in self.services:
            children = self._fetch_children(service)
            nodes = []
            for child in children:
                service_node = self._get_data(service, child)
                if service_node is not None:
                    nodes.append(service_node)
            service_nodes[service] = nodes
        return service_nodes

    def _fetch_children(self, service):
        path = self._get_path(service)
        try:
            children = self.zk.get_children(path)
            return children
        except NoNodeError:
            self.logger.warning(f"No service nodes found for path:{path}")
            return []

    def _get_path(self, service):
        return f"/{self.path}/{service}"

    def _create_service_node(self, args):
        self.logger.info(f"{args}")
        return ServiceNode(**args)

    def _convert_to_service_node(self, node_data_bytes):
        try:
            return ServiceNode.create(node_data_bytes)
        except Exception:
            self.logger.exception("Unable to parse node data into ServiceNode")
            return None

    def _get_data(self, service, node):
        path = self._get_path(service)
        try:
            node_path = f"{path}/{node}"
            node_data_json, stats = self.zk.get(node_path)
            self.logger.debug(f"found {node_data_json}")
            return self._convert_to_service_node(node_data_json)
        except NoNodeError:
            self.logger.warning(f"No nodes found for path:{path}")
            return None
        except Exception:
            self.logger.exception("Something went wrong while getting node data")
            return None


class RangerServiceFinder(object):
    """
    Initialize this class to be able to start and create a service finder
    """

    def __init__(self,
                 cluster_details: ClusterDetails,
                 namespace: str,
                 services: list,
                 selector: Selector = RandomNodeSelector(),
                 criteria_filter: Criteria = None,
                 logger=None,
                 zombie_check_threshold_time_in_ms: int = 60000):
        """
        :param cluster_details: Zookeeper cluster details
        :param namespace: ranger namespace (name of org)
        :param services: services to be registered for finding
        :param selector: custom selector logic when selecting one of the many healthy nodes available for the service
        :param criteria_filter: custom filter on nodes, based on data being present in the nodes
        :param logger: for logging
        :param zombie_check_threshold_time_in_ms: maximum time, beyond which, node will be considered unhealthy,
        if their lastUpdatedTimestamp has not changed
        """
        self._cluster_details = cluster_details
        self._services = services
        self._namespace = namespace
        self.is_running = False
        self._selector = selector
        self._logger = logger if logger is not None else get_default_logger()
        self._ranger_client = _RangerClient(
            KazooClient(hosts=self._cluster_details.zk_string,
                        read_only=True,  # since we will only be doing reading for finding services
                        # proper infinite retries to ensure we handle network flakiness
                        connection_retry=KazooRetry(max_tries=float('inf'), delay=0.2, max_delay=2)),
            self._namespace,
            self._services,
            self._logger)
        self._job = None
        self._criteria_filter = criteria_filter
        self._service_mapping = {}
        self._zombie_check_threshold_time_in_ms = zombie_check_threshold_time_in_ms

    def _stop_zk_updates(self):
        if not self.is_running:
            self._logger.info("Already stopped")
            return
        self._logger.info("Stopping all updates from zk and cleaning up..")
        self._job.stop()
        self._ranger_client.stop()
        self.is_running = False

    def _check_zk_updates(self):
        """
        Used to perform a single tick update to zookeeper. Handles error scenarios. Does healthcheck if necessary
        """
        try:
            new_mappings = self._ranger_client.get_nodes()
            if new_mappings is not None:
                self._service_mapping = new_mappings
        except Exception:
            self._logger.exception("Error while updating zk")

    def start(self, inline=False):
        """
        Creates a Thread that checks for updates in zookeeper at regular intervals
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
            self._job = Job(timedelta(seconds=self._cluster_details.update_interval_in_secs), self._check_zk_updates)
        finally:
            _release_lock()

        if inline:
            self._check_zk_updates()
        self._job.daemon = True
        self._job.start()

    def stop(self):
        """
        Stop zookeeper updates
        """
        self._stop_zk_updates()

    def _is_service_node_healthy(self, node: ServiceNode):
        return node.healthcheck_status == HealthcheckStatus.HEALTHY \
               and current_milli_time() - node.last_updated_timestamp <= self._zombie_check_threshold_time_in_ms

    def get_node(self, service):
        """
        :param service:
        :return: one of the healthy nodes using the registered selector logic, None if there are no nodes
        """
        return self._selector.select(self.get_all_nodes(service))

    def get_all_nodes(self, service):
        """
        :param service: service for which nodes are being fetched
        :return: all nodes that match the criteria and are healthy
        """
        if not self.is_running:
            self._logger.error("get_node() being called before start()")
            raise RangerFinderNotStartedException("get_node() being called before start()")
        if service not in self._services:
            self._logger.warning(f"service:{service} not registered in ServiceFinder. Registered:{self._services}")
            return None
        if service not in self._service_mapping:
            self._logger.warning(f"No nodes found for service:{service}")
            return None
        nodes = self._service_mapping[service]
        if len(nodes) == 0:
            self._logger.warning(f"No nodes found for service:{service}")
            return None
        healthy_nodes = list(filter(lambda x: self._is_service_node_healthy(x), nodes))
        if self._criteria_filter is not None:
            healthy_nodes = list(filter(lambda x: self._criteria_filter.filter(x), nodes))
        return healthy_nodes
