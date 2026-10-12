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

import pytest

from serviceprovider.ranger_daemon import initial_program_setup
from transport.http import HttpNodeDataSink
from transport.zk import ZkNodeDataSink


class TestTransportSelection:
    def test_defaults_to_zookeeper(self):
        provider = initial_program_setup(['-zk', 'localhost:2181', '-s', 'myapp', '-host', 'h', '-p', '1', '-e', 'stage'])

        assert isinstance(provider._ranger_client.sink, ZkNodeDataSink)

    def test_http_transport_builds_an_http_sink(self):
        provider = initial_program_setup(['--transport', 'http', '--hub-host', 'hub.local', '--hub-port', '8080',
                                          '-s', 'myapp', '-host', 'h', '-p', '1', '-e', 'stage'])

        assert isinstance(provider._ranger_client.sink, HttpNodeDataSink)
        assert provider._ranger_client.sink.config.host == 'hub.local'
        assert provider._ranger_client.sink.config.port == 8080

    def test_http_transport_requires_a_hub_host(self):
        with pytest.raises(ValueError):
            initial_program_setup(['--transport', 'http', '-s', 'myapp', '-host', 'h', '-p', '1', '-e', 'stage'])

    def test_zk_transport_requires_a_connection_string(self):
        with pytest.raises(ValueError):
            initial_program_setup(['-s', 'myapp', '-host', 'h', '-p', '1', '-e', 'stage'])


class TestNodeData:
    def test_legacy_fields_build_a_shard_info(self):
        provider = initial_program_setup(['-zk', 'localhost:2181', '-s', 'myapp', '-host', 'h', '-p', '1',
                                          '-e', 'stage', '-r', 'r1', '-t', 'a,b'])

        node_data = provider._service_details.get_node_data()

        assert node_data.environment == 'stage'
        assert node_data.region == 'r1'
        assert node_data.tags == ['a', 'b']

    def test_explicit_node_data_json_takes_precedence(self):
        provider = initial_program_setup(['-zk', 'localhost:2181', '-s', 'myapp', '-host', 'h', '-p', '1',
                                          '-e', 'stage', '--node-data-json', '{"shardId": 3}'])

        assert provider._service_details.get_node_data() == {"shardId": 3}

    def test_port_scheme_and_routing_weight_are_forwarded(self):
        provider = initial_program_setup(['-zk', 'localhost:2181', '-s', 'myapp', '-host', 'h', '-p', '1',
                                          '-e', 'stage', '--port-scheme', 'https', '--routing-weight', '2.5'])

        assert provider._service_details.port_scheme == 'https'
        assert provider._service_details.routing_weight == 2.5

    def test_hierarchical_environment_is_accepted_as_is(self):
        provider = initial_program_setup(['-zk', 'localhost:2181', '-s', 'myapp', '-host', 'h', '-p', '1',
                                          '-e', 'prod.region2.cell5'])

        assert provider._service_details.environment == 'prod.region2.cell5'
