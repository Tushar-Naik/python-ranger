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

from common.helper import current_milli_time
from rangermodels.ranger_models import (
    ClusterDetails,
    HealthcheckStatus,
    NodeData,
    ServiceNode,
)
from servicefinder.criteria import Criteria
from servicefinder.service_finder import RangerServiceFinder

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
