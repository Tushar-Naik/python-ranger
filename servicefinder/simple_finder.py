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
Single-service finders that pair a :class:`~servicefinder.serviceregistry.ServiceRegistry`
with a :class:`~servicefinder.shardselector.ShardSelector` over a
:class:`~transport.base.NodeDataSource`.

``RangerServiceFinder`` continues to manage one or more services behind the
same API it always has; these classes are the finer-grained building block
a :class:`~servicefinderhub.finder_hub.ServiceFinderHub` (or any caller wanting
explicit control of a single service) composes directly.
"""

from common.helper import current_milli_time, get_default_logger
from rangermodels.ranger_models import HealthcheckStatus, Service, ServiceNode
from servicefinder.node_selector import RandomNodeSelector, Selector
from servicefinder.serviceregistry import ListBasedServiceRegistry, MapBasedServiceRegistry
from servicefinder.shardselector import ListShardSelector, MatchingShardSelector, NoopShardSelector, ShardSelector
from transport.base import NodeDataSource


class SimpleServiceFinder(object):
    """
    Refreshes a single service's :class:`ServiceRegistry` from a
    :class:`NodeDataSource` and answers queries against the healthy subset.

    This does not manage its own background thread; call :meth:`refresh`
    yourself on whatever schedule you need (:class:`RangerServiceFinder` and
    :class:`~servicefinderhub.finder_hub.ServiceFinderHub` both do this on a
    timer).
    """

    def __init__(self,
                 service: Service,
                 source: NodeDataSource,
                 registry,
                 shard_selector: ShardSelector,
                 selector: Selector = None,
                 logger=None,
                 zombie_check_threshold_time_in_ms: int = 60000):
        self.service = service
        self.source = source
        self.registry = registry
        self.shard_selector = shard_selector
        self.selector = selector if selector is not None else RandomNodeSelector()
        self.logger = logger if logger is not None else get_default_logger()
        self.zombie_check_threshold_time_in_ms = zombie_check_threshold_time_in_ms
        self._last_refresh_failed = False

    def _is_healthy(self, node: ServiceNode):
        return (node.healthcheck_status == HealthcheckStatus.HEALTHY
                and current_milli_time() - node.last_updated_timestamp <= self.zombie_check_threshold_time_in_ms)

    def refresh(self):
        """
        Pull the latest nodes from the source and update the registry.
        A failed lookup leaves the registry untouched rather than clearing it.
        """
        nodes = self.source.nodes(self.service)
        if nodes is None:
            self.logger.warning(f"Keeping the previous view of service:{self.service.name()}")
            self._last_refresh_failed = True
            return
        self._last_refresh_failed = False
        self.registry.update(nodes)

    def get_all_nodes(self, criteria=None):
        """
        :param criteria: see :mod:`servicefinder.shardselector`
        :return: healthy nodes matching the criteria
        """
        candidates = self.shard_selector.nodes(criteria, self.registry)
        return [node for node in candidates if self._is_healthy(node)]

    def get_node(self, criteria=None):
        """
        :param criteria: see :mod:`servicefinder.shardselector`
        :return: one healthy, matching node chosen by the configured selector, or None
        """
        return self.selector.select(self.get_all_nodes(criteria))


class SimpleUnshardedServiceFinder(SimpleServiceFinder):
    """
    A finder for services where every healthy node is interchangeable.
    """

    def __init__(self, service: Service, source: NodeDataSource, selector: Selector = None, logger=None,
                 zombie_check_threshold_time_in_ms: int = 60000):
        super().__init__(service, source, ListBasedServiceRegistry(service), NoopShardSelector(),
                         selector=selector, logger=logger,
                         zombie_check_threshold_time_in_ms=zombie_check_threshold_time_in_ms)


class SimpleShardedServiceFinder(SimpleServiceFinder):
    """
    A finder for services partitioned by node data, looked up with a
    :class:`~servicefinder.shardselector.MatchingShardSelector` for O(1) bucket
    access rather than a linear scan.
    """

    def __init__(self, service: Service, source: NodeDataSource, selector: Selector = None, logger=None,
                 zombie_check_threshold_time_in_ms: int = 60000):
        super().__init__(service, source, MapBasedServiceRegistry(service), MatchingShardSelector(),
                         selector=selector, logger=logger,
                         zombie_check_threshold_time_in_ms=zombie_check_threshold_time_in_ms)
