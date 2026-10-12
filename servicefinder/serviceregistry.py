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
In-memory caches of the nodes currently known for a service.

A registry is refreshed wholesale on every poll (``update()`` replaces the
entire view) and read concurrently by request-handling threads, so reads must
never observe a partially updated state. Both implementations achieve this by
swapping an immutable snapshot behind a single reference rather than mutating
in place.
"""

import threading
from abc import ABC, abstractmethod

from rangermodels.ranger_models import Service


def _freeze(value):
    """
    Turn an arbitrary node data payload into something hashable, so it can be
    used as a dictionary key.

    nodeData is deliberately untyped (see serialize_node_data), which is
    precisely why it is not hashable out of the box: plain dicts and lists
    are not hashable in python. This produces a structurally equal, hashable
    stand-in (dicts become a frozenset of items, lists/sets become tuples),
    recursively, so two nodes published with equal but distinct dict instances
    still land in the same bucket.

    :param value: any node data payload, including None
    :return: a hashable key with the same equality semantics as ``value``
    """
    if isinstance(value, dict):
        return ('__dict__', frozenset((key, _freeze(val)) for key, val in value.items()))
    if isinstance(value, (list, tuple)):
        return ('__seq__', tuple(_freeze(item) for item in value))
    if isinstance(value, set):
        return ('__set__', frozenset(_freeze(item) for item in value))
    try:
        hash(value)
        return value
    except TypeError:
        # last resort for custom objects that are not hashable either; falls
        # back to identity, which at least does not raise
        return ('__id__', id(value))


class ServiceRegistry(ABC):
    """
    Holds the most recently fetched nodes for a single service.
    """

    def __init__(self, service: Service):
        self.service = service

    @abstractmethod
    def node_list(self):
        """
        :return: every node currently known for this service, regardless of nodeData
        """

    @abstractmethod
    def update(self, nodes):
        """
        Replace the current view with a freshly fetched list of nodes.

        :param nodes: list of ServiceNode
        """


class ListBasedServiceRegistry(ServiceRegistry):
    """
    A flat, unbucketed view. Used for unsharded services, where every healthy
    node is as good as any other.
    """

    def __init__(self, service: Service):
        super().__init__(service)
        self._nodes = ()

    def node_list(self):
        return list(self._nodes)

    def update(self, nodes):
        self._nodes = tuple(nodes)


class MapBasedServiceRegistry(ServiceRegistry):
    """
    A view bucketed by node data, so that nodes serving the same shard can be
    looked up without scanning the whole list.
    """

    def __init__(self, service: Service):
        super().__init__(service)
        self._buckets = {}
        self._nodes = ()
        self._lock = threading.Lock()

    def node_list(self):
        return list(self._nodes)

    def nodes(self):
        """
        :return: mapping of node data to the list of nodes publishing it. The
        key is a hashable, frozen stand-in for the original node data (see
        :func:`_freeze`); use :meth:`nodes_for` to look up by the original value.
        """
        return dict(self._buckets)

    def nodes_for(self, node_data):
        """
        :param node_data: a node data value, as originally published
        :return: nodes whose node data equals this value
        """
        return list(self._buckets.get(_freeze(node_data), []))

    def update(self, nodes):
        buckets = {}
        for node in nodes:
            key = _freeze(node.get_node_data())
            buckets.setdefault(key, []).append(node)
        with self._lock:
            self._buckets = buckets
            self._nodes = tuple(nodes)
