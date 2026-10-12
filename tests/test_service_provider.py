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
import logging
from unittest import mock

from rangermodels.ranger_models import (
    UNSET_TIMESTAMP,
    HealthcheckStatus,
    PortSchemes,
    ServiceDetails,
)
from serviceprovider.service_provider import _RangerClient
from transport.zk import ZkNodeDataSink

LOGGER = logging.getLogger("test")


def _client(service_details, exists=False):
    zk = mock.Mock()
    zk.connected = True
    zk.exists.return_value = exists
    sink = ZkNodeDataSink(client=zk, logger=LOGGER)
    return zk, _RangerClient(sink, service_details, LOGGER)


def _published(zk):
    """Decode the payload handed to zookeeper by the last update_tick()."""
    if zk.create.called:
        return json.loads(zk.create.call_args[0][1].decode("utf-8"))
    return json.loads(zk.set.call_args[0][1].decode("utf-8"))


class TestPublishedNodePayload:
    def test_publishes_full_field_set(self):
        details = ServiceDetails(host="h", port=8080, environment="stage", namespace="ns",
                                 service_name="svc", region="r1", tags=["a"],
                                 port_scheme=PortSchemes.HTTPS, routing_weight=2.0)
        zk, client = _client(details)

        client.update_tick(HealthcheckStatus.HEALTHY)

        payload = _published(zk)
        assert payload["host"] == "h"
        assert payload["port"] == 8080
        assert payload["portScheme"] == "https"
        assert payload["routingWeight"] == 2.0
        assert payload["healthcheckStatus"] == "healthy"
        assert payload["nodeData"] == {"environment": "stage", "region": "r1", "tags": ["a"]}

    def test_publishes_custom_node_data(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc",
                                 node_data={"shardId": 3, "version": "1.2.3"})
        zk, client = _client(details)

        client.update_tick(HealthcheckStatus.HEALTHY)

        assert _published(zk)["nodeData"] == {"shardId": 3, "version": "1.2.3"}

    def test_creates_ephemeral_node_when_absent(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        zk, client = _client(details, exists=False)

        client.update_tick(HealthcheckStatus.HEALTHY)

        zk.ensure_path.assert_called_once_with("/ns/svc")
        assert zk.create.call_args[1]["ephemeral"] is True

    def test_updates_in_place_when_present(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        zk, client = _client(details, exists=True)

        client.update_tick(HealthcheckStatus.HEALTHY)

        assert zk.set.called
        assert not zk.create.called


class TestHealthySinceTimestamp:
    def test_unset_while_unhealthy(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        zk, client = _client(details, exists=True)

        client.update_tick(HealthcheckStatus.UNHEALTHY)

        assert _published(zk)["healthySinceTimeStamp"] == UNSET_TIMESTAMP

    def test_pinned_to_the_first_healthy_tick(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        zk, client = _client(details, exists=True)

        client.update_tick(HealthcheckStatus.HEALTHY)
        first = _published(zk)["healthySinceTimeStamp"]
        client.update_tick(HealthcheckStatus.HEALTHY)
        second = _published(zk)["healthySinceTimeStamp"]

        assert first != UNSET_TIMESTAMP
        assert first == second
        # it marks the start of the healthy streak, not the latest update
        assert second <= _published(zk)["lastUpdatedTimeStamp"]

    def test_reset_after_an_unhealthy_tick(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        zk, client = _client(details, exists=True)

        client.update_tick(HealthcheckStatus.HEALTHY)
        first = _published(zk)["healthySinceTimeStamp"]
        client.update_tick(HealthcheckStatus.UNHEALTHY)
        client.update_tick(HealthcheckStatus.HEALTHY)
        third = _published(zk)["healthySinceTimeStamp"]

        assert third != UNSET_TIMESTAMP
        assert third >= first
