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

import pytest

from rangermodels.ranger_models import (
    UNSET_TIMESTAMP,
    ClusterDetails,
    HealthcheckStatus,
    PortSchemes,
    ServiceDetails,
)
from serviceprovider.service_provider import RangerServiceProvider, _RangerClient
from transport.base import NodeDataSink
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

    @pytest.mark.parametrize("node_data", [[1, 2], "shard-7", 7, 0.5, False])
    def test_publishes_json_native_node_data(self, node_data):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc",
                                 node_data=node_data)
        zk, client = _client(details)

        client.update_tick(HealthcheckStatus.HEALTHY)

        assert _published(zk)["nodeData"] == node_data

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

        with mock.patch("serviceprovider.service_provider.current_milli_time", side_effect=[1000, 2000]):
            client.update_tick(HealthcheckStatus.HEALTHY)
            first = _published(zk)
            client.update_tick(HealthcheckStatus.HEALTHY)
            second = _published(zk)

        assert first["healthySinceTimeStamp"] == 1000
        assert second["lastUpdatedTimeStamp"] == 2000
        # it marks the start of the healthy streak, not the latest update
        assert second["healthySinceTimeStamp"] == 1000

    def test_reset_after_an_unhealthy_tick(self):
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        zk, client = _client(details, exists=True)

        with mock.patch("serviceprovider.service_provider.current_milli_time", side_effect=[1000, 2000, 3000]):
            client.update_tick(HealthcheckStatus.HEALTHY)
            first = _published(zk)["healthySinceTimeStamp"]
            client.update_tick(HealthcheckStatus.UNHEALTHY)
            after_unhealthy = _published(zk)["healthySinceTimeStamp"]
            client.update_tick(HealthcheckStatus.HEALTHY)
            third = _published(zk)["healthySinceTimeStamp"]

        assert first == 1000
        assert after_unhealthy == UNSET_TIMESTAMP
        # the new streak starts at the third tick, not the first one
        assert third == 3000


class _StrictSink(NodeDataSink):
    """
    In-memory sink that, like a real registry, refuses heartbeats for nodes it does not know.
    """

    def __init__(self):
        self.nodes = {}
        self.calls = []
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def is_active(self):
        return True

    def register(self, service, node):
        self.calls.append("register")
        self.nodes[(service, node.representation())] = node
        return node

    def update_health(self, service, node):
        self.calls.append("update_health")
        key = (service, node.representation())
        if key not in self.nodes:
            return None
        self.nodes[key] = node
        return node

    def deregister(self, service, node):
        self.calls.append("deregister")
        self.nodes.pop((service, node.representation()), None)


DETAILS = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")


class TestRegistration:
    def test_first_tick_registers_then_updates(self):
        sink = _StrictSink()
        client = _RangerClient(sink, DETAILS, LOGGER)
        client.start()

        assert client.update_tick(HealthcheckStatus.HEALTHY) is not None
        assert client.update_tick(HealthcheckStatus.HEALTHY) is not None

        assert sink.calls == ["register", "update_health"]
        assert len(sink.nodes) == 1

    def test_reregisters_after_the_registration_is_lost(self):
        sink = _StrictSink()
        client = _RangerClient(sink, DETAILS, LOGGER)
        client.start()
        client.update_tick(HealthcheckStatus.HEALTHY)

        # the registry dropped the node (eg: session expiry / hub eviction)
        sink.nodes.clear()
        assert client.update_tick(HealthcheckStatus.HEALTHY) is None
        assert client.update_tick(HealthcheckStatus.HEALTHY) is not None

        assert sink.calls == ["register", "update_health", "register"]
        assert len(sink.nodes) == 1

    def test_reregisters_after_a_restart(self):
        sink = _StrictSink()
        client = _RangerClient(sink, DETAILS, LOGGER)
        client.start()
        client.update_tick(HealthcheckStatus.HEALTHY)

        client.start()
        client.update_tick(HealthcheckStatus.HEALTHY)

        assert sink.calls == ["register", "register"]

    def test_reregisters_after_a_publish_error(self):
        sink = _StrictSink()
        client = _RangerClient(sink, DETAILS, LOGGER)
        client.update_tick(HealthcheckStatus.HEALTHY)

        with mock.patch.object(sink, "update_health", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                client.update_tick(HealthcheckStatus.HEALTHY)
        client.update_tick(HealthcheckStatus.HEALTHY)

        assert sink.calls == ["register", "register"]


class TestDeregistrationOnStop:
    def test_stop_deregisters_the_published_node_before_stopping_the_sink(self):
        sink = mock.Mock(wraps=_StrictSink())
        client = _RangerClient(sink, DETAILS, LOGGER)
        client.update_tick(HealthcheckStatus.HEALTHY)

        client.stop()

        assert [c[0] for c in sink.method_calls] == ["register", "deregister", "stop"]

    def test_stop_without_a_published_node_skips_deregister(self):
        sink = _StrictSink()
        _RangerClient(sink, DETAILS, LOGGER).stop()
        assert sink.calls == []
        assert sink.stopped == 1

    def test_stop_still_stops_the_sink_when_deregister_fails(self):
        sink = _StrictSink()
        client = _RangerClient(sink, DETAILS, LOGGER)
        client.update_tick(HealthcheckStatus.HEALTHY)

        with mock.patch.object(sink, "deregister", side_effect=RuntimeError("boom")):
            client.stop()

        assert sink.stopped == 1

    def test_provider_removes_its_znode_from_a_shared_client(self):
        # with a caller-owned kazoo client the connection outlives the provider, so the
        # ephemeral node would survive unless the provider deletes it explicitly
        zk = mock.Mock()
        zk.connected = True
        zk.exists.return_value = False
        sink = ZkNodeDataSink(client=zk, logger=LOGGER)
        provider = RangerServiceProvider(ClusterDetails("unused", update_interval_in_secs=3600), DETAILS,
                                         logger=LOGGER, node_data_sink=sink)

        provider.start()
        provider._ranger_update_tick()
        provider.stop()

        zk.create.assert_called_once()
        zk.delete.assert_called_once_with("/ns/svc/h:8080")
        # the shared client belongs to the caller and must stay open
        zk.stop.assert_not_called()



class TestMultiMonitorAggregation:
    """
    RangerServiceProvider's published status should be healthy only while the
    legacy health_check (if configured) and every enabled, non-stale monitor
    all agree the service is healthy.
    """

    def _provider(self, health_check=None, health_monitors=None):
        from rangermodels.ranger_models import ClusterDetails
        from serviceprovider.service_provider import RangerServiceProvider

        sink = mock.Mock()
        sink.register.side_effect = lambda service, node: node
        sink.update_health.side_effect = lambda service, node: node
        details = ServiceDetails(host="h", port=8080, namespace="ns", service_name="svc")
        provider = RangerServiceProvider(ClusterDetails("x:2181"), details, health_check=health_check,
                                         logger=LOGGER, node_data_sink=sink, health_monitors=health_monitors)
        return provider, sink

    def _published_status(self, sink):
        published = [c for c in sink.method_calls if c[0] in ("register", "update_health")]
        return published[-1][1][1].healthcheck_status

    def _monitor(self, status, disabled=False, stale=False):
        monitor = mock.Mock()
        monitor.is_disabled.return_value = disabled
        monitor.has_valid_updated_time.return_value = not stale
        monitor.get_health_status.return_value = status
        monitor.name = "mock-monitor"
        return monitor

    def test_healthy_when_everything_agrees(self):
        provider, sink = self._provider(health_monitors=[self._monitor(HealthcheckStatus.HEALTHY)])

        provider._ranger_update_tick()

        assert self._published_status(sink) == HealthcheckStatus.HEALTHY

    def test_unhealthy_when_any_monitor_is_unhealthy(self):
        provider, sink = self._provider(health_monitors=[
            self._monitor(HealthcheckStatus.HEALTHY),
            self._monitor(HealthcheckStatus.UNHEALTHY),
        ])

        provider._ranger_update_tick()

        assert self._published_status(sink) == HealthcheckStatus.UNHEALTHY

    def test_a_disabled_unhealthy_monitor_is_ignored(self):
        provider, sink = self._provider(health_monitors=[
            self._monitor(HealthcheckStatus.UNHEALTHY, disabled=True),
        ])

        provider._ranger_update_tick()

        assert self._published_status(sink) == HealthcheckStatus.HEALTHY

    def test_a_stale_monitor_is_treated_as_unhealthy_even_if_its_last_result_was_healthy(self):
        provider, sink = self._provider(health_monitors=[
            self._monitor(HealthcheckStatus.HEALTHY, stale=True),
        ])

        provider._ranger_update_tick()

        assert self._published_status(sink) == HealthcheckStatus.UNHEALTHY

    def test_legacy_health_check_still_applies_alongside_monitors(self):
        failing_check = mock.Mock()
        failing_check.is_healthy.return_value = False
        provider, sink = self._provider(health_check=failing_check,
                                        health_monitors=[self._monitor(HealthcheckStatus.HEALTHY)])

        provider._ranger_update_tick()

        assert self._published_status(sink) == HealthcheckStatus.UNHEALTHY

    def test_no_monitors_behaves_as_before(self):
        provider, sink = self._provider()

        provider._ranger_update_tick()

        assert self._published_status(sink) == HealthcheckStatus.HEALTHY

    def test_monitors_are_started_and_stopped_with_the_provider(self):
        monitor = self._monitor(HealthcheckStatus.HEALTHY)
        provider, _ = self._provider(health_monitors=[monitor])

        provider.start()
        monitor.start.assert_called_once()
        provider.stop()
        monitor.stop.assert_called_once()
