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
from unittest import mock

import pytest
from kazoo.exceptions import NoNodeError

from rangermodels.ranger_models import (HealthcheckStatus, LegacyNodeData, PortSchemes, Service, ServiceNode)
from transport.zk import ZkNodeDataSink, ZkNodeDataSource, node_path, service_root_path

SERVICE = Service("testns", "testsvc")


def _zk(connected=True):
    zk = mock.Mock()
    zk.connected = connected
    return zk


def _payload(host="h1", port=8080, **kwargs):
    node = ServiceNode(host, port, **kwargs)
    return json.dumps(node.to_dict()).encode()


class TestPaths:

    def test_service_root_path(self):
        assert service_root_path(SERVICE) == "/testns/testsvc"

    def test_node_path_uses_host_port_representation(self):
        assert node_path(SERVICE, ServiceNode("h1", 8080)) == "/testns/testsvc/h1:8080"


class TestConnectorLifecycle:

    def test_start_skips_an_already_connected_client(self):
        zk = _zk(connected=True)
        ZkNodeDataSource(client=zk).start()
        zk.start.assert_not_called()

    def test_start_connects_a_disconnected_client(self):
        zk = _zk(connected=False)
        ZkNodeDataSource(client=zk).start()
        zk.start.assert_called_once()

    def test_stop_leaves_a_caller_owned_client_alone(self):
        zk = _zk()
        ZkNodeDataSource(client=zk).stop()
        zk.stop.assert_not_called()

    def test_stop_closes_a_self_built_client(self):
        source = ZkNodeDataSource(zk_string="localhost:2181")
        source.zk = _zk()
        source.stop()
        source.zk.stop.assert_called_once()

    def test_is_active_tracks_the_client(self):
        zk = _zk(connected=False)
        source = ZkNodeDataSource(client=zk)
        assert source.is_active() is False
        zk.connected = True
        assert source.is_active() is True

    def test_requires_a_client_or_a_connection_string(self):
        with pytest.raises(ValueError):
            ZkNodeDataSource()


class TestZkNodeDataSource:

    def test_nodes_reads_every_child(self):
        zk = _zk()
        zk.get_children.return_value = ["h1:8080", "h2:8080"]
        zk.get.side_effect = [(_payload("h1"), None), (_payload("h2"), None)]

        nodes = ZkNodeDataSource(client=zk).nodes(SERVICE)

        zk.get_children.assert_called_once_with("/testns/testsvc")
        assert [node.host for node in nodes] == ["h1", "h2"]

    def test_nodes_returns_empty_list_for_an_unknown_service(self):
        zk = _zk()
        zk.get_children.side_effect = NoNodeError()
        assert ZkNodeDataSource(client=zk).nodes(SERVICE) == []

    def test_nodes_returns_none_when_the_listing_fails(self):
        # None tells the finder to keep its previous view instead of blanking out
        zk = _zk()
        zk.get_children.side_effect = RuntimeError("boom")
        assert ZkNodeDataSource(client=zk).nodes(SERVICE) is None

    def test_nodes_skips_a_node_that_vanished_mid_read(self):
        zk = _zk()
        zk.get_children.return_value = ["h1:8080", "h2:8080"]
        zk.get.side_effect = [NoNodeError(), (_payload("h2"), None)]

        nodes = ZkNodeDataSource(client=zk).nodes(SERVICE)

        assert [node.host for node in nodes] == ["h2"]

    def test_nodes_skips_unparseable_payloads(self):
        zk = _zk()
        zk.get_children.return_value = ["h1:8080", "h2:8080"]
        zk.get.side_effect = [(b"not json", None), (_payload("h2"), None)]

        nodes = ZkNodeDataSource(client=zk).nodes(SERVICE)

        assert [node.host for node in nodes] == ["h2"]

    def test_nodes_applies_the_node_data_deserializer(self):
        zk = _zk()
        zk.get_children.return_value = ["h1:8080"]
        zk.get.return_value = (_payload(node_data={"environment": "stage", "region": "r1"}), None)

        source = ZkNodeDataSource(client=zk, node_data_deserializer=LegacyNodeData.from_dict)
        node = source.nodes(SERVICE)[0]

        assert isinstance(node.node_data, LegacyNodeData)
        assert node.node_data.environment == "stage"

    def test_nodes_keeps_node_data_as_a_mapping_by_default(self):
        zk = _zk()
        zk.get_children.return_value = ["h1:8080"]
        zk.get.return_value = (_payload(node_data={"shardId": 7}), None)

        node = ZkNodeDataSource(client=zk).nodes(SERVICE)[0]

        assert node.node_data == {"shardId": 7}

    def test_services_lists_the_namespace_children(self):
        zk = _zk()
        zk.get_children.return_value = ["svc-a", "svc-b"]

        services = ZkNodeDataSource(client=zk, namespace="testns").services()

        zk.get_children.assert_called_once_with("/testns")
        assert services == {Service("testns", "svc-a"), Service("testns", "svc-b")}

    def test_services_is_empty_without_a_namespace(self):
        assert ZkNodeDataSource(client=_zk()).services() == set()

    def test_services_is_empty_for_an_unknown_namespace(self):
        zk = _zk()
        zk.get_children.side_effect = NoNodeError()
        assert ZkNodeDataSource(client=zk, namespace="testns").services() == set()

    def test_services_is_empty_when_the_listing_fails(self):
        zk = _zk()
        zk.get_children.side_effect = RuntimeError("boom")
        assert ZkNodeDataSource(client=zk, namespace="testns").services() == set()


class TestZkNodeDataSink:

    def test_register_creates_an_ephemeral_node(self):
        zk = _zk()
        zk.exists.return_value = False
        node = ServiceNode("h1", 8080, node_data={"shardId": 7}, port_scheme=PortSchemes.HTTPS)

        assert ZkNodeDataSink(client=zk).register(SERVICE, node) is node

        zk.ensure_path.assert_called_once_with("/testns/testsvc")
        path, payload = zk.create.call_args[0]
        assert path == "/testns/testsvc/h1:8080"
        assert zk.create.call_args[1]["ephemeral"] is True
        assert json.loads(payload.decode()) == node.to_dict()

    def test_register_sets_an_existing_node_without_recreating_it(self):
        zk = _zk()
        zk.exists.return_value = True

        ZkNodeDataSink(client=zk).register(SERVICE, ServiceNode("h1", 8080))

        zk.create.assert_not_called()
        zk.ensure_path.assert_not_called()
        assert zk.set.call_args[0][0] == "/testns/testsvc/h1:8080"

    def test_update_health_publishes_the_refreshed_payload(self):
        zk = _zk()
        zk.exists.return_value = True
        node = ServiceNode("h1", 8080, healthcheck_status=HealthcheckStatus.UNHEALTHY)

        ZkNodeDataSink(client=zk).update_health(SERVICE, node)

        payload = json.loads(zk.set.call_args[0][1].decode())
        assert payload["healthcheckStatus"] == "unhealthy"

    def test_publish_returns_none_on_failure(self):
        zk = _zk()
        zk.exists.side_effect = RuntimeError("boom")
        assert ZkNodeDataSink(client=zk).register(SERVICE, ServiceNode("h1", 8080)) is None

    def test_deregister_deletes_the_node(self):
        zk = _zk()
        ZkNodeDataSink(client=zk).deregister(SERVICE, ServiceNode("h1", 8080))
        zk.delete.assert_called_once_with("/testns/testsvc/h1:8080")

    def test_deregister_tolerates_an_already_removed_node(self):
        zk = _zk()
        zk.delete.side_effect = NoNodeError()
        ZkNodeDataSink(client=zk).deregister(SERVICE, ServiceNode("h1", 8080))

    def test_deregister_swallows_transport_errors(self):
        zk = _zk()
        zk.delete.side_effect = RuntimeError("boom")
        ZkNodeDataSink(client=zk).deregister(SERVICE, ServiceNode("h1", 8080))

    def test_custom_node_data_serializer_is_used(self):
        zk = _zk()
        zk.exists.return_value = False

        class _Payload:
            pass

        ZkNodeDataSink(client=zk, node_data_serializer=lambda _: {"custom": True}).register(
            SERVICE, ServiceNode("h1", 8080, node_data=_Payload()))

        payload = json.loads(zk.create.call_args[0][1].decode())
        assert payload["nodeData"] == {"custom": True}
