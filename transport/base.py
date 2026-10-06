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
Transport abstractions shared by the service finder and the service provider.

Ranger supports more than one registry backend. The data model and the
discovery/publishing logic are identical across backends, only the way nodes are
read and written differs. These two interfaces capture that difference:

``NodeDataSource``
    the read side, used by service finders to discover nodes.
``NodeDataSink``
    the write side, used by service providers to publish their own node.

Implementations are expected to be safe to ``start()``/``stop()`` more than once.
"""

from abc import ABC, abstractmethod

from rangermodels.ranger_models import Service, ServiceNode


class NodeDataStoreConnector(ABC):
    """
    Common lifecycle shared by every source and sink implementation.
    """

    @abstractmethod
    def start(self):
        """
        Establish whatever connection the backend needs. Must be idempotent.
        """

    @abstractmethod
    def stop(self):
        """
        Release the underlying connection. Must be idempotent.
        """

    @abstractmethod
    def is_active(self):
        """
        :return: True when the connector is usable for reads/writes
        """


class NodeDataSource(NodeDataStoreConnector):
    """
    Read side of a registry backend.
    """

    @abstractmethod
    def nodes(self, service: Service):
        """
        :param service: service whose nodes are being looked up
        :return: list of ServiceNode currently published for the service. An
        empty list means the service is known but has no nodes; None means the
        lookup failed and the caller should keep its previous view.
        """

    @abstractmethod
    def services(self):
        """
        :return: set of Service currently known to the backend. Implementations
        that cannot enumerate services should return an empty set rather than
        raising.
        """


class NodeDataSink(NodeDataStoreConnector):
    """
    Write side of a registry backend.
    """

    @abstractmethod
    def register(self, service: Service, node: ServiceNode):
        """
        Publish a node for the first time.

        :return: the node as acknowledged by the backend, or None on failure
        """

    @abstractmethod
    def update_health(self, service: Service, node: ServiceNode):
        """
        Publish a refreshed heartbeat/health state for an already registered node.

        :return: the node as acknowledged by the backend, or None on failure
        """

    @abstractmethod
    def deregister(self, service: Service, node: ServiceNode):
        """
        Remove a previously published node. Backends with ephemeral semantics may
        implement this as a no-op beyond dropping the local connection.
        """
