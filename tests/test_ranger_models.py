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

from rangermodels.ranger_models import HealthcheckStatus, ServiceNode


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
            "nodeData": {},
            "healthcheckStatus": "healthy",
            "lastUpdatedTimeStamp": 1700000000000,
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

        assert node.get_node_data().environment == "stage"
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
