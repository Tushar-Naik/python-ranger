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
End to end tests against a real Zookeeper, exercising the provider and finder
through the full stack (kazoo included) rather than mocking the transport.

Deselected by default (see pytest.ini); requires a reachable Zookeeper, pointed
to via the ZK_CONNECTION_STRING environment variable (default localhost:2181).
CI runs these against a real zookeeper service container; there is no docker
available in the environment these were authored in, so they could not be run
locally during development -- review the CI run on the pull request for the
actual pass/fail signal.
"""

import os
import time

import pytest
from kazoo.client import KazooClient

from rangermodels.ranger_models import ClusterDetails, HealthcheckStatus, ServiceDetails
from servicefinder.service_finder import RangerServiceFinder
from serviceprovider.service_provider import RangerServiceProvider

pytestmark = pytest.mark.integration

ZK_CONNECTION_STRING = os.environ.get("ZK_CONNECTION_STRING", "localhost:2181")


@pytest.fixture
def namespace():
    # unique-ish per test run so repeated runs against a shared zk don't collide
    return f"it-test-{int(time.time() * 1000)}"


def _wait_for(predicate, timeout_seconds=10, interval_seconds=0.2):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval_seconds)
    return predicate()


class TestZookeeperRoundTrip:
    def test_a_published_node_is_discovered_and_healthy(self, namespace):
        provider = RangerServiceProvider(
            ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
            ServiceDetails(host="it-host", port=12345, namespace=namespace, service_name="svc",
                          node_data={"shardId": 1}))
        finder = RangerServiceFinder(ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
                                     namespace, ["svc"])
        try:
            provider.start()
            finder.start()

            node = _wait_for(lambda: finder.get_node("svc"))

            assert node is not None
            assert node.get_host() == "it-host"
            assert node.get_port() == 12345
            assert node.healthcheck_status == HealthcheckStatus.HEALTHY
            assert node.get_node_data() == {"shardId": 1}
        finally:
            provider.stop()
            finder.stop()

    def test_the_node_disappears_once_the_provider_stops(self, namespace):
        provider = RangerServiceProvider(
            ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
            ServiceDetails(host="it-host", port=12345, namespace=namespace, service_name="svc"))
        finder = RangerServiceFinder(ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
                                     namespace, ["svc"])
        try:
            provider.start()
            finder.start()
            _wait_for(lambda: finder.get_node("svc"))

            provider.stop()

            # the ephemeral znode is removed when the provider's zk session closes
            assert _wait_for(lambda: finder.get_all_nodes("svc") == []) == []
        finally:
            finder.stop()

    def test_an_unhealthy_provider_is_filtered_out_by_the_finder(self, namespace):
        failing_check = type("AlwaysUnhealthy", (), {"is_healthy": lambda self: False})()
        provider = RangerServiceProvider(
            ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
            ServiceDetails(host="it-host", port=12345, namespace=namespace, service_name="svc"),
            health_check=failing_check)
        finder = RangerServiceFinder(ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
                                     namespace, ["svc"])
        try:
            provider.start()
            finder.start()

            # the node exists in zk, but is never reported healthy
            time.sleep(1)

            assert finder.get_node("svc") is None
        finally:
            provider.stop()
            finder.stop()

    def test_plain_kazoo_can_read_what_the_provider_published(self, namespace):
        """
        Sanity check that the wire format is genuinely what a non-python,
        kazoo/curator-based reader would see -- not just what this client's own
        deserializer accepts.
        """
        provider = RangerServiceProvider(
            ClusterDetails(ZK_CONNECTION_STRING, update_interval_in_secs=0.2),
            ServiceDetails(host="it-host", port=12345, namespace=namespace, service_name="svc"))
        zk = KazooClient(hosts=ZK_CONNECTION_STRING)
        try:
            provider.start()
            zk.start()

            path = f"/{namespace}/svc/it-host:12345"
            payload, _ = _wait_for(lambda: zk.get(path) if zk.exists(path) else None)

            import json
            decoded = json.loads(payload)
            assert decoded["host"] == "it-host"
            assert decoded["port"] == 12345
            assert decoded["healthcheckStatus"] == "healthy"
            assert "portScheme" in decoded
            assert "routingWeight" in decoded
        finally:
            provider.stop()
            zk.stop()
