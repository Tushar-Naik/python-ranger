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
HTTP hub transport.

Many deployments do not expose the underlying registry (zookeeper, for example)
to clients at all. Instead a ranger hub server fronts the registry and speaks a
small REST protocol. This module implements the client side of that protocol.

Endpoints::

    GET  /ranger/services/v1                            -> {"data": [ {namespace, serviceName}, ... ]}
    GET  /ranger/nodes/v1/{namespace}/{serviceName}      -> {"data": [ <service node>, ... ]}
    POST /ranger/nodes/v1/add/{namespace}/{serviceName}  -> {"data": <service node>}

The responses are wrapped in a ``data`` envelope. Implementations tolerate a bare
list/object as well, so a minimal hub implementation is still usable.
"""

import requests

from common.helper import get_default_logger
from rangermodels.ranger_models import Service, ServiceNode, serialize_node_data
from transport.base import NodeDataSink, NodeDataSource

SERVICES_PATH = '/ranger/services/v1'
NODES_PATH = '/ranger/nodes/v1'
ADD_NODE_PATH = '/ranger/nodes/v1/add'

DEFAULT_CONNECTION_TIMEOUT_MS = 10000
DEFAULT_OPERATION_TIMEOUT_MS = 10000
DEFAULT_REFRESH_INTERVAL_MS = 10000


class HttpClientConfig:
    """
    Connection settings for a ranger hub endpoint.

    :param host: hub hostname
    :param port: hub port
    :param secure: use https when True
    :param connection_timeout_ms: time allowed to establish the connection
    :param operation_timeout_ms: time allowed for the server to respond
    :param refresh_interval_millis: hint for callers polling this hub
    :param replication_source: optional value sent as the replicationSource
    query parameter, used by hubs that replicate registrations
    """

    def __init__(self,
                 host,
                 port=80,
                 secure=False,
                 connection_timeout_ms=DEFAULT_CONNECTION_TIMEOUT_MS,
                 operation_timeout_ms=DEFAULT_OPERATION_TIMEOUT_MS,
                 refresh_interval_millis=DEFAULT_REFRESH_INTERVAL_MS,
                 replication_source=None):
        if not host:
            raise ValueError('host is mandatory for an http hub client')
        self.host = host
        self.port = port
        self.secure = secure
        self.connection_timeout_ms = connection_timeout_ms
        self.operation_timeout_ms = operation_timeout_ms
        self.refresh_interval_millis = refresh_interval_millis
        self.replication_source = replication_source

    def scheme(self):
        return 'https' if self.secure else 'http'

    def base_url(self):
        return '{scheme}://{host}:{port}'.format(scheme=self.scheme(), host=self.host, port=self.port)

    def timeout(self):
        """
        :return: the (connect, read) timeout tuple understood by requests
        """
        return self.connection_timeout_ms / 1000.0, self.operation_timeout_ms / 1000.0

    def to_dict(self):
        return {
            'host': self.host,
            'port': self.port,
            'secure': self.secure,
            'connectionTimeoutMs': self.connection_timeout_ms,
            'operationTimeoutMs': self.operation_timeout_ms,
            'refreshIntervalMillis': self.refresh_interval_millis,
            'replicationSource': self.replication_source,
        }

    def __repr__(self):
        return 'HttpClientConfig({})'.format(self.to_dict())


def _unwrap(payload):
    """
    Pull the actual payload out of the ``data`` envelope used by the hub.
    """
    if isinstance(payload, dict) and 'data' in payload:
        return payload.get('data')
    return payload


class _HttpConnector:
    """
    Shared plumbing for the http source and sink.

    The connector owns a ``requests.Session`` unless one is supplied, in which
    case the caller keeps ownership and ``stop()`` leaves it alone.
    """

    def __init__(self, config: HttpClientConfig, logger=None, session=None):
        if config is None:
            raise ValueError('an HttpClientConfig is mandatory for an http hub client')
        self.config = config
        self.logger = logger if logger else get_default_logger()
        self._owns_session = session is None
        self.session = session
        self._active = session is not None

    def start(self):
        if self.session is None:
            self.session = requests.Session()
        self._active = True

    def stop(self):
        self._active = False
        if not self._owns_session:
            return
        session, self.session = self.session, None
        if session is None:
            return
        try:
            session.close()
        except Exception as e:
            self.logger.warning('Error while closing the http session. Error:{error}'.format(error=e))

    def is_active(self):
        return self._active and self.session is not None

    def _url(self, path):
        return self.config.base_url() + path

    def _params(self):
        if self.config.replication_source:
            return {'replicationSource': self.config.replication_source}
        return None

    def _request(self, method, path, json_body=None):
        """
        :return: the decoded ``data`` payload, or None when the call failed
        """
        if self.session is None:
            self.start()
        url = self._url(path)
        try:
            response = self.session.request(method,
                                            url,
                                            json=json_body,
                                            params=self._params(),
                                            timeout=self.config.timeout())
        except Exception as e:
            self.logger.warning('Error while calling the ranger hub. url:{url} error:{error}'
                                .format(url=url, error=e))
            return None
        if response.status_code < 200 or response.status_code >= 300:
            self.logger.warning('Unexpected response from the ranger hub. url:{url} status:{status}'
                                .format(url=url, status=response.status_code))
            return None
        try:
            return _unwrap(response.json())
        except Exception as e:
            self.logger.warning('Unparseable response from the ranger hub. url:{url} error:{error}'
                                .format(url=url, error=e))
            return None


class HttpNodeDataSource(_HttpConnector, NodeDataSource):
    """
    Reads nodes and the service catalogue from a ranger hub over http.
    """

    def __init__(self, config: HttpClientConfig, logger=None, session=None, node_data_deserializer=None):
        _HttpConnector.__init__(self, config, logger=logger, session=session)
        self._node_data_deserializer = node_data_deserializer

    def nodes(self, service: Service):
        path = '{base}/{namespace}/{service_name}'.format(base=NODES_PATH,
                                                          namespace=service.namespace,
                                                          service_name=service.service_name)
        payload = self._request('GET', path)
        if payload is None:
            return None
        if not isinstance(payload, list):
            self.logger.warning('Expected a list of nodes for service:{service}'.format(service=service.name()))
            return None
        nodes = []
        for node_json in payload:
            try:
                nodes.append(ServiceNode.from_dict(node_json, node_data_deserializer=self._node_data_deserializer))
            except Exception as e:
                self.logger.warning('Skipping an unparseable node for service:{service}. Error:{error}'
                                    .format(service=service.name(), error=e))
        return nodes

    def services(self):
        payload = self._request('GET', SERVICES_PATH)
        if payload is None:
            return set()
        if not isinstance(payload, list):
            self.logger.warning('Expected a list of services from the ranger hub')
            return set()
        services = set()
        for service_json in payload:
            try:
                services.add(Service.from_dict(service_json))
            except Exception as e:
                self.logger.warning('Skipping an unparseable service entry. Error:{error}'.format(error=e))
        return services


class HttpNodeDataSink(_HttpConnector, NodeDataSink):
    """
    Publishes nodes to a ranger hub over http.

    The hub owns node expiry, so there is no explicit delete endpoint in the
    protocol. ``deregister`` therefore only drops the local session.
    """

    def __init__(self, config: HttpClientConfig, logger=None, session=None, node_data_serializer=None):
        _HttpConnector.__init__(self, config, logger=logger, session=session)
        self._node_data_serializer = node_data_serializer if node_data_serializer else serialize_node_data

    def register(self, service: Service, node: ServiceNode):
        return self._publish(service, node)

    def update_health(self, service: Service, node: ServiceNode):
        return self._publish(service, node)

    def deregister(self, service: Service, node: ServiceNode):
        """
        The hub ages nodes out on its own, so there is nothing to call here.
        """
        self.logger.debug('Hub registrations expire on their own. Nothing to deregister for service:{service}'
                          .format(service=service.name()))

    def _publish(self, service: Service, node: ServiceNode):
        path = '{base}/{namespace}/{service_name}'.format(base=ADD_NODE_PATH,
                                                          namespace=service.namespace,
                                                          service_name=service.service_name)
        body = node.to_dict(node_data_serializer=self._node_data_serializer)
        payload = self._request('POST', path, json_body=body)
        if payload is None:
            return None
        try:
            return ServiceNode.from_dict(payload)
        except Exception as e:
            self.logger.warning('Unparseable registration response for service:{service}. Error:{error}'
                                .format(service=service.name(), error=e))
            return None
