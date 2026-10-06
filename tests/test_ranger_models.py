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

import pytest

from rangermodels.ranger_models import (
    UNSET_TIMESTAMP,
    HealthcheckStatus,
    LegacyNodeData,
    NodeData,
    PortSchemes,
    Service,
    ServiceDetails,
    ServiceNode,
    serialize_node_data,
)


class TestServiceNodeDeserialization:
    def test_round_trip_without_node_data(self):
        """
        Regression test: create() leaves node_data unset when the payload carries no
        nodeData key, and to_dict() then dereferenced it unconditionally.
        """
        payload = json.dumps({
            "host": "host-1",
            "port": 8080,
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(payload.encode("utf-8"))

        assert node.get_node_data() is None
        assert node.to_dict() == {
            "host": "host-1",
            "port": 8080,
            "portScheme": "http",
            "nodeData": {},
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
            "healthySinceTimeStamp": UNSET_TIMESTAMP,
            "routingWeight": 1.0,
        }

    def test_round_trip_with_node_data(self):
        payload = json.dumps({
            "host": "host-1",
            "port": 8080,
            "nodeData": {"environment": "stage", "region": "r1", "tags": ["a"]},
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(payload.encode("utf-8"))

        # node data stays a plain mapping by default, it is deliberately untyped
        assert node.get_node_data() == {"environment": "stage", "region": "r1", "tags": ["a"]}
        assert node.to_dict()["nodeData"] == {
            "environment": "stage",
            "region": "r1",
            "tags": ["a"],
        }

    def test_unhealthy_status_is_parsed(self):
        payload = json.dumps({
            "host": "host-1",
            "port": 8080,
            "healthcheckStatus": "unhealthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(payload.encode("utf-8"))

        assert node.healthcheck_status == HealthcheckStatus.UNHEALTHY

    def test_accessors(self):
        payload = json.dumps({
            "host": "host-1",
            "port": 8080,
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(payload.encode("utf-8"))

        assert node.get_host() == "host-1"
        assert node.get_port() == 8080
        assert node.get_host_port() == ("host-1", 8080)
        assert node.get_endpoint() == "http://host-1:8080"
        assert node.get_endpoint(secure=True) == "https://host-1:8080"


class TestGenericNodeData:
    """
    Node data is declared as a generic by the reference implementation. Anything
    json serializable must survive a round trip untouched.
    """

    @pytest.mark.parametrize("payload", [
        {"shardId": 7, "version": "1.4.2"},
        {"nested": {"a": [1, 2, 3]}},
        {},
    ])
    def test_arbitrary_mapping_round_trips(self, payload):
        wire = json.dumps({
            "host": "host-1",
            "port": 8080,
            "nodeData": payload,
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(wire.encode("utf-8"))

        assert node.get_node_data() == payload
        assert node.to_dict()["nodeData"] == payload

    def test_custom_deserializer_is_applied(self):
        wire = json.dumps({
            "host": "host-1",
            "port": 8080,
            "nodeData": {"environment": "stage", "region": "r1", "tags": ["a"]},
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(wire.encode("utf-8"), node_data_deserializer=LegacyNodeData.from_dict)

        assert node.get_node_data() == LegacyNodeData("stage", "r1", ["a"])

    def test_objects_exposing_to_dict_are_serialized(self):
        node = ServiceNode(host="h", port=1, node_data=LegacyNodeData("stage", "r1", ["a"]))

        assert node.to_dict()["nodeData"] == {"environment": "stage", "region": "r1", "tags": ["a"]}

    def test_unserializable_node_data_is_rejected(self):
        with pytest.raises(TypeError):
            serialize_node_data(object())

    def test_legacy_alias_is_preserved(self):
        assert NodeData is LegacyNodeData


class TestServiceNodeNewFields:
    """
    routingWeight, healthySinceTimeStamp and portScheme post date the last
    release of this client and were silently dropped on both read and write.
    """

    def test_new_fields_are_parsed(self):
        wire = json.dumps({
            "host": "host-1",
            "port": 8080,
            "portScheme": "https",
            "routingWeight": 2.5,
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
            "healthySinceTimeStamp": 1699999999000,
        })

        node = ServiceNode.create(wire.encode("utf-8"))

        assert node.get_port_scheme() == PortSchemes.HTTPS
        assert node.get_routing_weight() == 2.5
        assert node.healthy_since_timestamp == 1699999999000

    def test_new_fields_default_when_absent(self):
        """A node published by an older peer must still deserialize."""
        wire = json.dumps({
            "host": "host-1",
            "port": 8080,
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
        })

        node = ServiceNode.create(wire.encode("utf-8"))

        assert node.get_port_scheme() == PortSchemes.HTTP
        assert node.get_routing_weight() == 1.0
        assert node.healthy_since_timestamp == UNSET_TIMESTAMP

    def test_endpoint_follows_advertised_port_scheme(self):
        node = ServiceNode(host="h", port=443, port_scheme=PortSchemes.HTTPS)

        assert node.get_endpoint() == "https://h:443"
        # an explicit override still wins, which keeps the old call sites working
        assert node.get_endpoint(secure=False) == "http://h:443"

    def test_representation(self):
        assert ServiceNode(host="h", port=80).representation() == "h:80"


class TestHealthcheckStatusParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("healthy", HealthcheckStatus.HEALTHY),
        ("HEALTHY", HealthcheckStatus.HEALTHY),
        ("unhealthy", HealthcheckStatus.UNHEALTHY),
        ("something-new", HealthcheckStatus.UNHEALTHY),
    ])
    def test_parse(self, raw, expected):
        assert HealthcheckStatus.parse(raw) == expected

    def test_parse_none_returns_default(self):
        assert HealthcheckStatus.parse(None, default=HealthcheckStatus.HEALTHY) == HealthcheckStatus.HEALTHY

    def test_parse_passes_through_enum(self):
        assert HealthcheckStatus.parse(HealthcheckStatus.UNHEALTHY) == HealthcheckStatus.UNHEALTHY


class TestService:
    def test_name(self):
        assert Service("ns", "svc").name() == "ns/svc"

    def test_round_trip(self):
        service = Service("ns", "svc")
        assert Service.from_dict(service.to_dict()) == service

    def test_usable_as_a_dict_key(self):
        assert {Service("ns", "svc"): 1}[Service("ns", "svc")] == 1

    def test_ordering(self):
        assert sorted([Service("ns", "b"), Service("ns", "a")]) == [Service("ns", "a"), Service("ns", "b")]


class TestServiceDetails:
    def test_falls_back_to_legacy_node_data(self):
        details = ServiceDetails(host="h", port=1, environment="stage", namespace="ns",
                                 service_name="svc", region="r1", tags=["a"])

        assert details.get_node_data() == LegacyNodeData("stage", "r1", ["a"])

    def test_explicit_node_data_wins(self):
        details = ServiceDetails(host="h", port=1, environment="stage", namespace="ns",
                                 service_name="svc", node_data={"shardId": 3})

        assert details.get_node_data() == {"shardId": 3}

    def test_paths(self):
        details = ServiceDetails(host="h", port=1, namespace="ns", service_name="svc")

        assert details.get_root_path() == "/ns/svc"
        assert details.get_path() == "/ns/svc/h:1"
        assert details.get_service() == Service("ns", "svc")
