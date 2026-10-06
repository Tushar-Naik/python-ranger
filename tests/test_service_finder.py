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

from unittest import mock

import pytest

from common.exceptions import RangerFinderNotStartedException
from common.helper import current_milli_time
from rangermodels.ranger_models import (
    ClusterDetails,
    HealthcheckStatus,
    NodeData,
    ServiceNode,
)
from servicefinder.criteria import Criteria
from servicefinder.service_finder import RangerServiceFinder, _RangerClient

NAMESPACE = "testns"
SERVICE = "testsvc"


def _node(host, healthcheck_status=HealthcheckStatus.HEALTHY, age_ms=0, region="r1"):
    return ServiceNode(
        host=host,
        port=8080,
        node_data=NodeData(environment="stage", region=region, tags=None),
        healthcheck_status=healthcheck_status,
        last_updated_timestamp=current_milli_time() - age_ms,
    )


class _RegionCriteria(Criteria):
    def __init__(self, region):
        self._region = region

    def filter(self, node: ServiceNode):
        return node.get_node_data().region == self._region


def _finder(nodes, criteria_filter=None):
    """Builds a finder wired to a fixed node mapping, bypassing zookeeper entirely."""
    finder = RangerServiceFinder(
        cluster_details=ClusterDetails("localhost:2181"),
        namespace=NAMESPACE,
        services=[SERVICE],
        criteria_filter=criteria_filter,
    )
    finder.is_running = True
    finder._service_mapping = {SERVICE: nodes}
    return finder


class TestCriteriaFilterRespectsHealth:
    """
    Regression tests for the criteria filter being applied to the unfiltered node list,
    which silently discarded the healthcheck and zombie filtering.
    """

    def test_unhealthy_node_is_excluded_even_when_it_matches_criteria(self):
        healthy = _node("healthy-host", region="r1")
        unhealthy = _node("unhealthy-host", HealthcheckStatus.UNHEALTHY, region="r1")

        finder = _finder([healthy, unhealthy], criteria_filter=_RegionCriteria("r1"))

        hosts = [node.get_host() for node in finder.get_all_nodes(SERVICE)]
        assert hosts == ["healthy-host"]

    def test_zombie_node_is_excluded_even_when_it_matches_criteria(self):
        fresh = _node("fresh-host", region="r1")
        zombie = _node("zombie-host", age_ms=120000, region="r1")

        finder = _finder([fresh, zombie], criteria_filter=_RegionCriteria("r1"))

        hosts = [node.get_host() for node in finder.get_all_nodes(SERVICE)]
        assert hosts == ["fresh-host"]

    def test_criteria_still_narrows_the_healthy_set(self):
        r1 = _node("r1-host", region="r1")
        r2 = _node("r2-host", region="r2")

        finder = _finder([r1, r2], criteria_filter=_RegionCriteria("r1"))

        hosts = [node.get_host() for node in finder.get_all_nodes(SERVICE)]
        assert hosts == ["r1-host"]

    def test_health_filtering_without_criteria_is_unchanged(self):
        healthy = _node("healthy-host")
        unhealthy = _node("unhealthy-host", HealthcheckStatus.UNHEALTHY)

        finder = _finder([healthy, unhealthy])

        hosts = [node.get_host() for node in finder.get_all_nodes(SERVICE)]
        assert hosts == ["healthy-host"]

    def test_get_node_never_returns_an_unhealthy_node_under_criteria(self):
        healthy = _node("healthy-host", region="r1")
        unhealthy = _node("unhealthy-host", HealthcheckStatus.UNHEALTHY, region="r1")

        finder = _finder([healthy, unhealthy], criteria_filter=_RegionCriteria("r1"))

        for _ in range(20):
            assert finder.get_node(SERVICE).get_host() == "healthy-host"


class TestFinderClientStart:
    """
    Regression tests: the finder started its kazoo client unconditionally, unlike the
    provider, so a caller supplying an already connected client hit an exception.
    """

    def _client(self, connected):
        zk = mock.Mock()
        zk.connected = connected
        return _RangerClient(zk, NAMESPACE, [SERVICE], mock.Mock()), zk

    def test_disconnected_client_is_started(self):
        client, zk = self._client(connected=False)
        client.start()
        zk.start.assert_called_once_with()

    def test_already_connected_client_is_not_restarted(self):
        client, zk = self._client(connected=True)
        client.start()
        zk.start.assert_not_called()

    def test_stop_always_stops(self):
        client, zk = self._client(connected=True)
        client.stop()
        zk.stop.assert_called_once_with()


class TestFinderGuards:
    def test_get_all_nodes_before_start_raises(self):
        finder = RangerServiceFinder(ClusterDetails("localhost:2181"), NAMESPACE, [SERVICE])
        with pytest.raises(RangerFinderNotStartedException):
            finder.get_all_nodes(SERVICE)

    def test_unregistered_service_returns_none(self):
        finder = _finder([_node("host")])
        assert finder.get_all_nodes("unregistered") is None

    def test_service_with_no_mapping_returns_none(self):
        finder = _finder([_node("host")])
        finder._service_mapping = {}
        assert finder.get_all_nodes(SERVICE) is None

    def test_service_with_empty_node_list_returns_none(self):
        assert _finder([]).get_all_nodes(SERVICE) is None
