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
Shard selection.

A shard selector answers "which of the currently known nodes match this
criteria", given an in-memory :class:`~servicefinder.serviceregistry.ServiceRegistry`.
This is what lets one logical service have many instances, each serving a
different partition of data (a shard), and lets callers route to the instance
that actually owns the data they need instead of a random one.

Two calling conventions are accepted for the criteria, so existing code is not
broken by this addition:

* a plain ``callable(node_data) -> bool``, matching the reference
  implementation's predicate-over-node-data design
* a legacy :class:`~servicefinder.criteria.Criteria` instance, whose
  ``filter(node)`` is evaluated against the whole :class:`ServiceNode`
  (host, health status, and so on), exactly as :meth:`RangerServiceFinder.get_all_nodes`
  already does today

Passing ``None`` means "no filtering, return every node".
"""

from abc import ABC, abstractmethod

from servicefinder.criteria import Criteria
from servicefinder.serviceregistry import ListBasedServiceRegistry, MapBasedServiceRegistry, ServiceRegistry


def matches(criteria, node):
    """
    Normalizes the two accepted criteria shapes into a single boolean check
    against one node.

    :param criteria: ``None``, a ``callable(node_data) -> bool``, or a :class:`Criteria`
    :param node: the ServiceNode being evaluated
    :return: True when the node should be kept
    """
    if criteria is None:
        return True
    if isinstance(criteria, Criteria):
        return criteria.filter(node)
    return criteria(node.get_node_data())


class ShardSelector(ABC):
    """
    Selects the nodes of a registry that match a criteria.
    """

    @abstractmethod
    def nodes(self, criteria, registry: ServiceRegistry):
        """
        :param criteria: see module docstring
        :param registry: the in-memory view of the service's current nodes
        :return: list of matching ServiceNode
        """


class NoopShardSelector(ShardSelector):
    """
    Ignores the criteria entirely. This is what an unsharded service uses:
    every healthy node is as good as any other.
    """

    def nodes(self, criteria, registry: ServiceRegistry):
        return registry.node_list()


class ListShardSelector(ShardSelector):
    """
    Linear scan over a flat node list, evaluating the criteria against each node.
    """

    def nodes(self, criteria, registry: ListBasedServiceRegistry):
        if criteria is None:
            return registry.node_list()
        return [node for node in registry.node_list() if matches(criteria, node)]


class MatchingShardSelector(ShardSelector):
    """
    Looks up pre-bucketed nodes in a :class:`MapBasedServiceRegistry`.

    When the criteria is a plain predicate it is evaluated once per bucket
    against that bucket's node data, which is cheaper than scanning every node
    individually once there are many shards. A legacy :class:`Criteria` still
    needs the whole node, so those buckets are scanned node by node instead.
    """

    def nodes(self, criteria, registry: MapBasedServiceRegistry):
        if criteria is None:
            return registry.node_list()
        if isinstance(criteria, Criteria):
            return [node for node in registry.node_list() if criteria.filter(node)]
        matched = []
        for node_data, nodes in registry.nodes().items():
            # node_data here is the frozen stand-in used as the bucket key, not
            # the original payload; nodes_for/node_list always return real nodes,
            # so evaluate the predicate against a representative node's real data
            if nodes and criteria(nodes[0].get_node_data()):
                matched.extend(nodes)
        return matched
