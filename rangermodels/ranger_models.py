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
Wire models shared by the service provider and the service finder.

These mirror the models published by the reference implementation
(https://github.com/appform-io/ranger) so that nodes registered by a Python
service are discoverable by a Java client and vice versa.
"""

import json
from enum import Enum

from common.helper import safe_get

#: Sentinel used by the reference implementation for "never updated". It is
#: ``Long.MIN_VALUE`` on the wire, so it is reproduced exactly here.
UNSET_TIMESTAMP = -9223372036854775808


class HealthcheckStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"

    @classmethod
    def parse(cls, value, default=None):
        """
        Lenient parser for the ``healthcheckStatus`` wire field.

        Unknown values are treated as unhealthy, which is the safe default: an
        unrecognised status must never cause traffic to be routed to a node.

        :param value: raw wire value, may be ``None`` or an existing enum member
        :param default: returned when ``value`` is ``None``
        :return: HealthcheckStatus
        """
        if value is None:
            return default
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.UNHEALTHY


class UrlScheme(Enum):
    GET = 1
    POST = 2


class PortSchemes(object):
    """
    Transport scheme advertised alongside the port.

    Prior to its introduction every node was assumed to speak plain HTTP. It is
    still defaulted to ``http`` for that reason.
    """

    HTTP = "http"
    HTTPS = "https"
    TCP = "tcp"

    ALL = (HTTP, HTTPS, TCP)


def serialize_node_data(node_data):
    """
    Convert an arbitrary node data payload into something json serializable.

    ``nodeData`` is deliberately untyped: the reference implementation declares
    it as a generic, and deployments routinely publish custom attributes
    (shard id, version, datacenter, capacity, feature flags ...). Anything that
    is already a mapping is passed through, anything exposing ``to_dict()`` is
    asked to convert itself.

    :param node_data: payload to serialize, may be ``None``
    :return: json serializable representation, ``{}`` when there is no payload
    """
    if node_data is None:
        return {}
    if isinstance(node_data, dict):
        return node_data
    to_dict = getattr(node_data, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError(
        f"nodeData of type {type(node_data).__name__} is not json serializable. "
        f"Pass a dict, an object exposing to_dict(), or a custom serializer.")


class ShardInfo(object):
    """
    The conventional ``{environment, region, tags}`` node data payload.

    This is not a required shape -- ``nodeData`` is generic, see
    :func:`serialize_node_data` -- but it is the shape the reference
    implementation's own example servers publish: ``environment`` for
    prod/stage style deployment stages, ``region`` for the datacenter/cell a
    node runs in, and ``tags`` for anything else you want to filter or A/B on.
    It round-trips byte for byte with what this client published before
    nodeData became generic.

    :class:`~servicefinder.shardselector.HierarchicalEnvironmentAwareShardSelector`
    is built specifically around this shape's ``environment`` field.
    """

    def __init__(self, environment=None, region=None, tags=None):
        self.environment = environment
        self.region = region
        self.tags = tags

    @staticmethod
    def _is_none(val):
        return val is None or len(val) == 0

    @classmethod
    def from_dict(cls, node_data_json):
        """
        Deserializer suitable for passing to :meth:`ServiceNode.create`.

        :param node_data_json: raw ``nodeData`` mapping
        :return: ShardInfo
        """
        if node_data_json is None:
            return None
        return cls(environment=safe_get(node_data_json, 'environment'),
                   region=safe_get(node_data_json, 'region'),
                   tags=safe_get(node_data_json, 'tags'))

    def to_dict(self):
        if self.environment is None and self.region is None and self._is_none(self.tags):
            return {}
        return {"environment": self.environment, "region": self.region, "tags": self.tags}

    def _tags_key(self):
        return tuple(self.tags) if self.tags is not None else None

    def __eq__(self, other):
        if not isinstance(other, ShardInfo):
            return NotImplemented
        return (self.environment, self.region, self._tags_key()) == (other.environment, other.region,
                                                                     other._tags_key())

    def __hash__(self):
        return hash((self.environment, self.region, self._tags_key()))

    def __repr__(self):
        return f"ShardInfo(environment={self.environment!r}, region={self.region!r}, tags={self.tags!r})"


#: Backwards compatible aliases. Both names used to refer to this fixed shape
#: before node data became generic; ``ShardInfo`` is now the canonical name,
#: matching the reference implementation's own example node data class.
LegacyNodeData = ShardInfo
NodeData = ShardInfo


class Service(object):
    """
    A namespaced service name. Used as a key wherever a client deals with more
    than one service at a time.
    """

    def __init__(self, namespace: str, service_name: str):
        self.namespace = namespace
        self.service_name = service_name

    @classmethod
    def from_dict(cls, service_json):
        """
        :param service_json: mapping with ``namespace`` and ``serviceName``
        :return: Service
        """
        return cls(namespace=service_json['namespace'],
                   service_name=service_json['serviceName'])

    def name(self):
        """
        :return: fully qualified ``namespace/serviceName``
        """
        return f"{self.namespace}/{self.service_name}"

    def to_dict(self):
        return {"namespace": self.namespace, "serviceName": self.service_name}

    def __eq__(self, other):
        if not isinstance(other, Service):
            return NotImplemented
        return (self.namespace, self.service_name) == (other.namespace, other.service_name)

    def __lt__(self, other):
        if not isinstance(other, Service):
            return NotImplemented
        return (self.namespace, self.service_name) < (other.namespace, other.service_name)

    def __hash__(self):
        return hash((self.namespace, self.service_name))

    def __repr__(self):
        return f"Service(namespace={self.namespace!r}, service_name={self.service_name!r})"


class ServiceNode(object):
    """
    Represents a service that may be discoverable at a host:port over your favourite transport protocol
    """

    def __init__(self,
                 host: str,
                 port: int,
                 node_data=None,
                 healthcheck_status: HealthcheckStatus = HealthcheckStatus.HEALTHY,
                 last_updated_timestamp: int = UNSET_TIMESTAMP,
                 routing_weight: float = 1.0,
                 healthy_since_timestamp: int = UNSET_TIMESTAMP,
                 port_scheme: str = PortSchemes.HTTP):
        """
        :param host: hostname the node is reachable at
        :param port: port the node is reachable at
        :param node_data: arbitrary json serializable payload published with the node
        :param healthcheck_status: current health of the node
        :param last_updated_timestamp: epoch millis of the last published update
        :param routing_weight: relative weight used by weighted node selectors
        :param healthy_since_timestamp: epoch millis since which the node has been continuously healthy
        :param port_scheme: transport scheme of ``port``, one of :class:`PortSchemes`
        """
        self.host = host
        self.port = port
        self.node_data = node_data
        self.last_updated_timestamp = last_updated_timestamp
        self.healthcheck_status = healthcheck_status
        self.routing_weight = routing_weight
        self.healthy_since_timestamp = healthy_since_timestamp
        self.port_scheme = port_scheme

    @classmethod
    def from_dict(cls, node_json, node_data_deserializer=None):
        """
        Build a node from an already decoded mapping.

        :param node_json: decoded wire representation
        :param node_data_deserializer: optional callable applied to the raw
          ``nodeData`` mapping. Defaults to keeping the mapping as is, which
          keeps the payload generic.
        :return: ServiceNode
        """
        node_data = safe_get(node_json, 'nodeData')
        if node_data is not None and node_data_deserializer is not None:
            node_data = node_data_deserializer(node_data)

        last_updated_timestamp = safe_get(node_json, 'lastUpdatedTimeStamp')
        healthy_since_timestamp = safe_get(node_json, 'healthySinceTimeStamp')
        routing_weight = safe_get(node_json, 'routingWeight')
        port_scheme = safe_get(node_json, 'portScheme')

        return cls(host=node_json['host'],
                   port=int(node_json['port']),
                   node_data=node_data,
                   healthcheck_status=HealthcheckStatus.parse(safe_get(node_json, 'healthcheckStatus'),
                                                              default=HealthcheckStatus.HEALTHY),
                   last_updated_timestamp=(UNSET_TIMESTAMP if last_updated_timestamp is None
                                           else int(last_updated_timestamp)),
                   routing_weight=1.0 if routing_weight is None else float(routing_weight),
                   healthy_since_timestamp=(UNSET_TIMESTAMP if healthy_since_timestamp is None
                                            else int(healthy_since_timestamp)),
                   port_scheme=PortSchemes.HTTP if port_scheme is None else str(port_scheme))

    @classmethod
    def create(cls, bytes, node_data_deserializer=None):
        """
        use this factory method to create the ServiceNode from json serialized bytes

        :param bytes: json
        :param node_data_deserializer: optional callable applied to the raw ``nodeData`` mapping
        :return: ServiceNode
        """
        return cls.from_dict(json.loads(bytes), node_data_deserializer=node_data_deserializer)

    def to_dict(self, node_data_serializer=serialize_node_data):
        """
        :param node_data_serializer: callable turning the node data payload into
          something json serializable
        :return: wire representation of this node
        """
        return {"host": self.host,
                "port": self.port,
                "portScheme": self.port_scheme,
                "nodeData": node_data_serializer(self.node_data),
                "healthcheckStatus": self.healthcheck_status.value,
                "lastUpdatedTimeStamp": self.last_updated_timestamp,
                "healthySinceTimeStamp": self.healthy_since_timestamp,
                "routingWeight": self.routing_weight}

    def representation(self):
        """
        :return: ``host:port``, the identity of the node within a service
        """
        return f"{self.host}:{self.port}"

    def get_host(self):
        """
        :return: hostname
        """
        return self.host

    def get_host_port(self):
        """
        :return: host port pair
        """
        return self.host, self.port

    def get_endpoint(self, secure=None):
        """
        :param secure: forces https when ``True`` and http when ``False``. When
          left unset the advertised :attr:`port_scheme` is used.
        :return: endpoint URL
        """
        if secure is None:
            scheme = self.port_scheme or PortSchemes.HTTP
        else:
            scheme = PortSchemes.HTTPS if secure else PortSchemes.HTTP
        return f"{scheme}://{self.host}:{self.port}"

    def get_port(self):
        """
        :return: port
        """
        return self.port

    def get_port_scheme(self):
        """
        :return: transport scheme advertised for the port
        """
        return self.port_scheme

    def get_routing_weight(self):
        """
        :return: relative weight to be used by weighted selectors
        """
        return self.routing_weight

    def get_node_data(self):
        """
        :return: node data
        """
        return self.node_data

    def __repr__(self):
        return (f"ServiceNode(host={self.host!r}, port={self.port!r}, port_scheme={self.port_scheme!r}, "
                f"healthcheck_status={self.healthcheck_status}, node_data={self.node_data!r})")


class ServiceDetails(object):
    """
    Describes the node that a :class:`serviceprovider.RangerServiceProvider` publishes.
    """

    def __init__(self,
                 host,
                 port,
                 environment=None,
                 namespace=None,
                 service_name=None,
                 region=None,
                 tags=None,
                 node_data=None,
                 port_scheme=PortSchemes.HTTP,
                 routing_weight=1.0):
        """
        :param host: hostname this node is reachable at
        :param port: port this node is reachable at
        :param environment: convenience attribute published inside node data
        :param namespace: ranger namespace to publish under
        :param service_name: service to publish under
        :param region: convenience attribute published inside node data
        :param tags: convenience attribute published inside node data
        :param node_data: arbitrary json serializable payload. When supplied it
          fully replaces the environment/region/tags payload.
        :param port_scheme: transport scheme of ``port``, one of :class:`PortSchemes`
        :param routing_weight: relative weight used by weighted node selectors
        """
        self.host = host
        self.port = port
        self.namespace = namespace
        self.service_name = service_name
        self.environment = environment
        self.region = region
        self.tags = tags
        self.node_data = node_data
        self.port_scheme = port_scheme
        self.routing_weight = routing_weight

    def get_path(self):
        return f"/{self.namespace}/{self.service_name}/{self.host}:{self.port}"

    def get_root_path(self):
        return f"/{self.namespace}/{self.service_name}"

    def get_service(self):
        """
        :return: the :class:`Service` this node belongs to
        """
        return Service(self.namespace, self.service_name)

    def get_node_data(self):
        """
        :return: the payload to publish as ``nodeData``. Falls back to the
          legacy environment/region/tags shape when no explicit payload was given.
        """
        if self.node_data is not None:
            return self.node_data
        return LegacyNodeData(self.environment, self.region, self.tags)

    def to_dict(self):
        return {"host": self.host, "port": self.port, "environment": self.environment, "namespace": self.namespace,
                "service": self.service_name, "portScheme": self.port_scheme}


class ClusterDetails(object):
    def __init__(self, zk_string, update_interval_in_secs=1):
        self.zk_string = str(zk_string)
        self.update_interval_in_secs = update_interval_in_secs

    def to_dict(self):
        return {"zk_string": self.zk_string, "update_interval_in_secs": self.update_interval_in_secs}
