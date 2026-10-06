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
Zookeeper backed implementations of the transport interfaces.

The on-the-wire layout is unchanged from the pre 2.0 releases and matches the
java implementation:

* ``/{namespace}/{serviceName}`` holds one child per node
* each child is named ``{host}:{port}`` and is an ephemeral znode
* the payload is the json serialized ServiceNode
"""

import json

from kazoo.client import KazooClient
from kazoo.exceptions import NoNodeError
from kazoo.retry import KazooRetry

from common.helper import get_default_logger
from rangermodels.ranger_models import Service, ServiceNode, serialize_node_data
from transport.base import NodeDataSink, NodeDataSource


def service_root_path(service: Service):
    """
    :return: the znode under which all nodes of a service are published
    """
    return f"/{service.namespace}/{service.service_name}"


def node_path(service: Service, node: ServiceNode):
    """
    :return: the znode of a single published node
    """
    return f"{service_root_path(service)}/{node.representation()}"


def _reader_retry():
    # proper infinite retries to ensure we handle network flakiness
    return KazooRetry(max_tries=float('inf'), delay=0.2, max_delay=2)


def _writer_retry():
    return KazooRetry(max_tries=float('inf'), delay=1, max_delay=5)


class _ZkConnector(object):
    """
    Shared kazoo lifecycle handling. Both the source and the sink either accept a
    pre-built client (handy for tests and for sharing a single connection) or
    build one from a connection string.
    """

    def __init__(self, zk_string=None, client: KazooClient = None, logger=None, read_only=False,
                 connection_retry=None):
        if client is None and zk_string is None:
            raise ValueError("either zk_string or client must be supplied")
        self._logger = logger if logger is not None else get_default_logger()
        self._owns_client = client is None
        self.zk = client if client is not None else KazooClient(
            hosts=zk_string,
            read_only=read_only,
            connection_retry=connection_retry if connection_retry is not None else _reader_retry())

    def start(self):
        if not self.zk.connected:
            self.zk.start()

    def stop(self):
        if not self._owns_client:
            # the caller handed us the client, it owns the shutdown too
            return
        try:
            self.zk.stop()
        except Exception:
            self._logger.exception("Error while stopping the zookeeper client")

    def is_active(self):
        return bool(self.zk.connected)


class ZkNodeDataSource(_ZkConnector, NodeDataSource):
    """
    Reads nodes published by any ranger provider, java or python.
    """

    def __init__(self, zk_string=None, client: KazooClient = None, namespace=None, logger=None,
                 node_data_deserializer=None, connection_retry=None):
        """
        :param zk_string: zookeeper connection string, ignored when client is given
        :param client: pre-built kazoo client, whose lifecycle stays with the caller
        :param namespace: namespace used by services(); not needed for nodes()
        :param node_data_deserializer: optional callable applied to the raw nodeData mapping
        """
        _ZkConnector.__init__(self, zk_string=zk_string, client=client, logger=logger, read_only=True,
                              connection_retry=connection_retry)
        self._namespace = namespace
        self._node_data_deserializer = node_data_deserializer

    def nodes(self, service: Service):
        path = service_root_path(service)
        try:
            children = self.zk.get_children(path)
        except NoNodeError:
            self._logger.warning(f"No service nodes found for path:{path}")
            return []
        except Exception:
            self._logger.exception(f"Error while listing nodes at path:{path}")
            return None

        nodes = []
        for child in children:
            node = self._read_node(f"{path}/{child}")
            if node is not None:
                nodes.append(node)
        return nodes

    def services(self):
        if self._namespace is None:
            self._logger.warning("services() called on a source built without a namespace")
            return set()
        path = f"/{self._namespace}"
        try:
            children = self.zk.get_children(path)
        except NoNodeError:
            self._logger.warning(f"No services found for path:{path}")
            return set()
        except Exception:
            self._logger.exception(f"Error while listing services at path:{path}")
            return set()
        return {Service(self._namespace, child) for child in children}

    def _read_node(self, path):
        try:
            payload, _ = self.zk.get(path)
        except NoNodeError:
            # the node went away between the listing and the read, nothing to do
            return None
        except Exception:
            self._logger.exception(f"Error while reading node at path:{path}")
            return None
        try:
            return ServiceNode.create(payload, node_data_deserializer=self._node_data_deserializer)
        except Exception:
            self._logger.exception(f"Unable to parse node data into ServiceNode for path:{path}")
            return None


class ZkNodeDataSink(_ZkConnector, NodeDataSink):
    """
    Publishes the current node as an ephemeral znode.
    """

    def __init__(self, zk_string=None, client: KazooClient = None, logger=None, node_data_serializer=None,
                 connection_retry=None):
        _ZkConnector.__init__(self, zk_string=zk_string, client=client, logger=logger, read_only=False,
                              connection_retry=connection_retry if connection_retry is not None else _writer_retry())
        self._node_data_serializer = node_data_serializer if node_data_serializer is not None else serialize_node_data

    def register(self, service: Service, node: ServiceNode):
        return self._publish(service, node)

    def update_health(self, service: Service, node: ServiceNode):
        return self._publish(service, node)

    def deregister(self, service: Service, node: ServiceNode):
        path = node_path(service, node)
        try:
            self.zk.delete(path)
        except NoNodeError:
            # the ephemeral node is already gone, that is the desired end state
            pass
        except Exception:
            self._logger.exception(f"Error while deleting node at path:{path}")

    def _publish(self, service: Service, node: ServiceNode):
        path = node_path(service, node)
        payload = json.dumps(node.to_dict(node_data_serializer=self._node_data_serializer)).encode()
        try:
            if self.zk.exists(path):
                self.zk.set(path, payload)
            else:
                self.zk.ensure_path(service_root_path(service))
                self.zk.create(path, payload, ephemeral=True)
            return node
        except Exception:
            self._logger.exception(f"Error while publishing node at path:{path}")
            return None
