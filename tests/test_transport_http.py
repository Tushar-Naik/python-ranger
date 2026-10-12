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
Tests for the http hub transport.

These run against a real stub hub served by http.server on a loopback socket, so
the request/response wire format is exercised end to end without docker.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from common.helper import get_default_logger
from rangermodels.ranger_models import HealthcheckStatus, PortSchemes, Service, ServiceNode
from transport.http import HttpClientConfig, HttpNodeDataSink, HttpNodeDataSource

LOGGER = get_default_logger()
NAMESPACE = 'testns'
SERVICE_NAME = 'testsvc'
SERVICE = Service(NAMESPACE, SERVICE_NAME)


class _StubHub:
    """
    A tiny ranger hub. Routes are plugged in per test as
    ``(method, path) -> (status, body)`` where body is json serialised as is.
    """

    def __init__(self):
        self.routes = {}
        self.requests = []
        self._server = None
        self._thread = None

    def route(self, method, path, body, status=200):
        self.routes[(method, path)] = (status, body)

    def start(self):
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self, method):
                parsed = urlparse(self.path)
                length = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(length) if length else b''
                hub.requests.append({
                    'method': method,
                    'path': parsed.path,
                    'query': parse_qs(parsed.query),
                    'body': json.loads(raw) if raw else None,
                })
                status, body = hub.routes.get((method, parsed.path), (404, {'error': 'not found'}))
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                self._handle('GET')

            def do_POST(self):
                self._handle('POST')

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def port(self):
        return self._server.server_address[1]

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def hub():
    stub = _StubHub().start()
    yield stub
    stub.stop()


def _config(hub, **kwargs):
    return HttpClientConfig(host='127.0.0.1', port=hub.port, **kwargs)


def _node_json(host, port=8080, **overrides):
    payload = {
        'host': host,
        'port': port,
        'portScheme': 'http',
        'nodeData': {'environment': 'stage'},
        'healthcheckStatus': 'healthy',
        'lastUpdatedTimeStamp': 1234,
        'healthySinceTimeStamp': 1000,
        'routingWeight': 1.0,
    }
    payload.update(overrides)
    return payload


class TestHttpClientConfig:

    def test_base_url_is_plain_http_by_default(self):
        assert HttpClientConfig(host='hub', port=8080).base_url() == 'http://hub:8080'

    def test_base_url_switches_to_https_when_secure(self):
        assert HttpClientConfig(host='hub', port=443, secure=True).base_url() == 'https://hub:443'

    def test_timeout_is_a_connect_read_pair_in_seconds(self):
        config = HttpClientConfig(host='hub', connection_timeout_ms=1500, operation_timeout_ms=4000)
        assert config.timeout() == (1.5, 4.0)

    def test_host_is_mandatory(self):
        with pytest.raises(ValueError):
            HttpClientConfig(host=None)


class TestHttpNodeDataSource:

    def test_nodes_are_read_from_the_hub(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', {'data': [_node_json('host-1'), _node_json('host-2')]})
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)
        source.start()

        nodes = source.nodes(SERVICE)

        assert [node.get_host() for node in nodes] == ['host-1', 'host-2']
        assert nodes[0].healthcheck_status == HealthcheckStatus.HEALTHY
        assert nodes[0].port_scheme == PortSchemes.HTTP

    def test_all_node_fields_survive_the_round_trip(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc',
                  {'data': [_node_json('host-1', portScheme='https', routingWeight=2.5,
                                       healthySinceTimeStamp=42, healthcheckStatus='unhealthy')]})
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        node = source.nodes(SERVICE)[0]

        assert node.port_scheme == PortSchemes.HTTPS
        assert node.routing_weight == 2.5
        assert node.healthy_since_timestamp == 42
        assert node.healthcheck_status == HealthcheckStatus.UNHEALTHY
        assert node.get_endpoint() == 'https://host-1:8080'

    def test_a_bare_list_response_is_accepted(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', [_node_json('host-1')])
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert [node.get_host() for node in source.nodes(SERVICE)] == ['host-1']

    def test_an_empty_service_yields_an_empty_list(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', {'data': []})
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.nodes(SERVICE) == []

    def test_a_server_error_is_reported_as_a_failed_lookup(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', {'error': 'boom'}, status=500)
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.nodes(SERVICE) is None

    def test_an_unknown_service_is_reported_as_a_failed_lookup(self, hub):
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.nodes(Service(NAMESPACE, 'missing')) is None

    def test_an_unparseable_body_is_reported_as_a_failed_lookup(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', b'not json at all')
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.nodes(SERVICE) is None

    def test_a_single_bad_node_does_not_drop_the_good_ones(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', {'data': ['garbage', _node_json('host-2')]})
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert [node.get_host() for node in source.nodes(SERVICE)] == ['host-2']

    def test_the_node_data_deserializer_is_applied(self, hub):
        hub.route('GET', '/ranger/nodes/v1/testns/testsvc', {'data': [_node_json('host-1')]})
        source = HttpNodeDataSource(_config(hub),
                                    logger=LOGGER,
                                    node_data_deserializer=lambda raw: raw.get('environment'))

        assert source.nodes(SERVICE)[0].get_node_data() == 'stage'

    def test_services_are_read_from_the_catalogue(self, hub):
        hub.route('GET', '/ranger/services/v1', {'data': [{'namespace': NAMESPACE, 'serviceName': 'a'},
                                                          {'namespace': NAMESPACE, 'serviceName': 'b'}]})
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.services() == {Service(NAMESPACE, 'a'), Service(NAMESPACE, 'b')}

    def test_services_returns_an_empty_set_when_the_hub_fails(self, hub):
        hub.route('GET', '/ranger/services/v1', {'error': 'boom'}, status=503)
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.services() == set()

    def test_the_replication_source_is_sent_as_a_query_parameter(self, hub):
        hub.route('GET', '/ranger/services/v1', {'data': []})
        source = HttpNodeDataSource(_config(hub, replication_source='dc-1'), logger=LOGGER)

        source.services()

        assert hub.requests[-1]['query'] == {'replicationSource': ['dc-1']}

    def test_a_dead_hub_is_reported_as_a_failed_lookup(self):
        source = HttpNodeDataSource(HttpClientConfig(host='127.0.0.1', port=1, connection_timeout_ms=200,
                                                     operation_timeout_ms=200),
                                    logger=LOGGER)

        assert source.nodes(SERVICE) is None
        assert source.services() == set()


class TestHttpNodeDataSink:

    def test_registering_posts_the_full_node(self, hub):
        hub.route('POST', '/ranger/nodes/v1/add/testns/testsvc', {'data': _node_json('host-1')})
        sink = HttpNodeDataSink(_config(hub), logger=LOGGER)
        node = ServiceNode('host-1', 8080, node_data={'environment': 'stage'}, last_updated_timestamp=1234)

        published = sink.register(SERVICE, node)

        assert published.get_host() == 'host-1'
        body = hub.requests[-1]['body']
        assert body['host'] == 'host-1'
        assert body['port'] == 8080
        assert body['nodeData'] == {'environment': 'stage'}
        assert body['healthcheckStatus'] == 'healthy'
        assert body['lastUpdatedTimeStamp'] == 1234
        assert body['portScheme'] == 'http'
        assert body['routingWeight'] == 1.0

    def test_update_health_hits_the_same_endpoint(self, hub):
        hub.route('POST', '/ranger/nodes/v1/add/testns/testsvc', {'data': _node_json('host-1')})
        sink = HttpNodeDataSink(_config(hub), logger=LOGGER)
        node = ServiceNode('host-1', 8080, healthcheck_status=HealthcheckStatus.UNHEALTHY)

        assert sink.update_health(SERVICE, node) is not None
        assert hub.requests[-1]['path'] == '/ranger/nodes/v1/add/testns/testsvc'
        assert hub.requests[-1]['body']['healthcheckStatus'] == 'unhealthy'

    def test_a_rejected_registration_returns_none(self, hub):
        hub.route('POST', '/ranger/nodes/v1/add/testns/testsvc', {'error': 'boom'}, status=500)
        sink = HttpNodeDataSink(_config(hub), logger=LOGGER)

        assert sink.register(SERVICE, ServiceNode('host-1', 8080)) is None

    def test_the_node_data_serializer_is_applied(self, hub):
        hub.route('POST', '/ranger/nodes/v1/add/testns/testsvc', {'data': _node_json('host-1')})
        sink = HttpNodeDataSink(_config(hub), logger=LOGGER, node_data_serializer=lambda data: {'shard': data})

        sink.register(SERVICE, ServiceNode('host-1', 8080, node_data='s1'))

        assert hub.requests[-1]['body']['nodeData'] == {'shard': 's1'}

    def test_deregister_is_a_no_op(self, hub):
        sink = HttpNodeDataSink(_config(hub), logger=LOGGER)

        sink.deregister(SERVICE, ServiceNode('host-1', 8080))

        assert hub.requests == []


class TestConnectorLifecycle:

    def test_start_is_idempotent_and_creates_a_session(self, hub):
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)
        source.start()
        session = source.session
        source.start()

        assert source.session is session
        assert source.is_active() is True

    def test_stop_closes_an_owned_session(self, hub):
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)
        source.start()

        source.stop()

        assert source.is_active() is False
        assert source.session is None

    def test_stop_is_idempotent(self, hub):
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)
        source.start()
        source.stop()
        source.stop()

        assert source.is_active() is False

    def test_stop_leaves_a_caller_owned_session_alone(self, hub):
        import requests
        session = requests.Session()
        source = HttpNodeDataSource(_config(hub), logger=LOGGER, session=session)

        source.stop()

        assert source.session is session

    def test_a_request_starts_the_connector_lazily(self, hub):
        hub.route('GET', '/ranger/services/v1', {'data': []})
        source = HttpNodeDataSource(_config(hub), logger=LOGGER)

        assert source.is_active() is False
        source.services()
        assert source.is_active() is True

    def test_a_config_is_mandatory(self):
        with pytest.raises(ValueError):
            HttpNodeDataSource(None, logger=LOGGER)
