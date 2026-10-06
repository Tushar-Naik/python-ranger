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

from common.exceptions import RangerFinderNotStartedException
from common.job import Job
from rangermodels.ranger_models import ClusterDetails, Service, ServiceNode, HealthcheckStatus
from common.helper import get_default_logger, current_milli_time, default_serialize_func
from servicefinder.criteria import Criteria
from servicefinder.node_selector import Selector, RandomNodeSelector
from transport.base import NodeDataSource
from transport.zk import ZkNodeDataSource

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
    Pulls the nodes of every registered service out of the configured source.
    """

    def __init__(self, source: NodeDataSource, namespace, services, logger):
        self.source = source
        self.namespace = namespace
        self.services = services
        self.logger = logger

    def start(self):
        self.source.start()

    def stop(self):
        self.source.stop()

    def get_nodes(self, previous=None):
        """
        :param previous: the mapping currently held by the finder, used as the fallback
        for any service whose lookup failed
        :return: mapping of service name to its list of nodes
        """
        previous = previous if previous is not None else {}
        self.logger.debug(f"Fetching updates from the registry for {self.services}")
        service_nodes = {}
        for service in self.services:
            nodes = self.source.nodes(Service(self.namespace, service))
            if nodes is None:
                # the lookup failed, hold on to whatever we knew rather than
                # declaring the service node-less
                self.logger.warning(f"Keeping the previous view of service:{service}")
                nodes = previous.get(service, [])
            service_nodes[service] = nodes
        return service_nodes


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
                 zombie_check_threshold_time_in_ms: int = 60000,
                 node_data_deserializer=None,
                 node_data_source: NodeDataSource = None):
        """
        :param cluster_details: registry details; the zookeeper connection string is only read
        when the default zookeeper source is used, the update interval always applies
        :param namespace: ranger namespace (name of org)
        :param services: services to be registered for finding
        :param selector: custom selector logic when selecting one of the many healthy nodes available for the service
        :param criteria_filter: custom filter on nodes, based on data being present in the nodes
        :param logger: for logging
        :param zombie_check_threshold_time_in_ms: maximum time, beyond which, node will be considered unhealthy,
        if their lastUpdatedTimestamp has not changed
        :param node_data_deserializer: optional callable applied to the raw nodeData mapping of every discovered
        node. Node data is left as a plain mapping when this is not supplied, which keeps the payload generic.
        Pass ``LegacyNodeData.from_dict`` to get back the pre 2.0 environment/region/tags object.
        :param node_data_source: registry backend to read from. Defaults to zookeeper, built from
        cluster_details.zk_string
        """
        self._cluster_details = cluster_details
        self._services = services
        self._namespace = namespace
        self.is_running = False
        self._selector = selector
        self._logger = logger if logger is not None else get_default_logger()
        if node_data_source is None:
            node_data_source = ZkNodeDataSource(zk_string=self._cluster_details.zk_string,
                                                namespace=self._namespace,
                                                logger=self._logger,
                                                node_data_deserializer=node_data_deserializer)
        self._ranger_client = _RangerClient(node_data_source, self._namespace, self._services, self._logger)
        self._job = None
        self._criteria_filter = criteria_filter
        self._service_mapping = {}
        self._zombie_check_threshold_time_in_ms = zombie_check_threshold_time_in_ms

    def _stop_zk_updates(self):
        if not self.is_running:
            self._logger.info("Already stopped")
            return
        self._logger.info("Stopping all updates from the registry and cleaning up..")
        self._job.stop()
        self._ranger_client.stop()
        self.is_running = False

    def _check_zk_updates(self):
        """
        Perform a single refresh of the node view against the registry. Handles error scenarios.
        """
        try:
            new_mappings = self._ranger_client.get_nodes(self._service_mapping)
            if new_mappings is not None:
                self._service_mapping = new_mappings
        except Exception:
            self._logger.exception("Error while refreshing nodes from the registry")

    def start(self, inline=False):
        """
        Creates a Thread that checks the registry for updates at regular intervals
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
        Stop registry updates
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
            # the criteria filter narrows down the *healthy* nodes; it must never widen the
            # selection back out to the unfiltered node list
            healthy_nodes = list(filter(lambda x: self._criteria_filter.filter(x), healthy_nodes))
        return healthy_nodes
