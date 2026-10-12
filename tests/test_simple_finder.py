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

from rangermodels.ranger_models import HealthcheckStatus, Service, ServiceNode
from servicefinder.simple_finder import SimpleShardedServiceFinder, SimpleUnshardedServiceFinder

SERVICE = Service("ns", "svc")


def _node(host, node_data=None, healthy=True, age_ms=0):
    from common.helper import current_milli_time
    return ServiceNode(host, 8080, node_data=node_data,
                       healthcheck_status=HealthcheckStatus.HEALTHY if healthy else HealthcheckStatus.UNHEALTHY,
                       last_updated_timestamp=current_milli_time() - age_ms)


class TestSimpleUnshardedServiceFinder:
    def test_refresh_populates_the_registry(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("h1"), _node("h2")]
        finder = SimpleUnshardedServiceFinder(SERVICE, source)

        finder.refresh()

        assert sorted(n.get_host() for n in finder.get_all_nodes()) == ["h1", "h2"]
        source.nodes.assert_called_once_with(SERVICE)

    def test_unhealthy_nodes_are_excluded(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("h1"), _node("h2", healthy=False)]
        finder = SimpleUnshardedServiceFinder(SERVICE, source)
        finder.refresh()

        assert [n.get_host() for n in finder.get_all_nodes()] == ["h1"]

    def test_zombie_nodes_are_excluded(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("h1"), _node("h2", age_ms=120000)]
        finder = SimpleUnshardedServiceFinder(SERVICE, source, zombie_check_threshold_time_in_ms=60000)
        finder.refresh()

        assert [n.get_host() for n in finder.get_all_nodes()] == ["h1"]

    def test_a_failed_refresh_keeps_the_previous_nodes(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("h1")]
        finder = SimpleUnshardedServiceFinder(SERVICE, source)
        finder.refresh()

        source.nodes.return_value = None
        finder.refresh()

        assert [n.get_host() for n in finder.get_all_nodes()] == ["h1"]

    def test_get_node_uses_the_configured_selector(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("only")]
        finder = SimpleUnshardedServiceFinder(SERVICE, source)
        finder.refresh()

        assert finder.get_node().get_host() == "only"

    def test_criteria_is_ignored_for_unsharded_services(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("h1")]
        finder = SimpleUnshardedServiceFinder(SERVICE, source)
        finder.refresh()

        assert [n.get_host() for n in finder.get_all_nodes(criteria=lambda _: False)] == ["h1"]


class TestSimpleShardedServiceFinder:
    def test_criteria_selects_the_matching_shard(self):
        source = mock.Mock()
        source.nodes.return_value = [
            _node("h1", {"shardId": 1}),
            _node("h2", {"shardId": 2}),
        ]
        finder = SimpleShardedServiceFinder(SERVICE, source)
        finder.refresh()

        nodes = finder.get_all_nodes(criteria=lambda data: data["shardId"] == 2)

        assert [n.get_host() for n in nodes] == ["h2"]

    def test_unhealthy_nodes_in_the_matching_shard_are_excluded(self):
        source = mock.Mock()
        source.nodes.return_value = [
            _node("h1", {"shardId": 1}, healthy=True),
            _node("h2", {"shardId": 1}, healthy=False),
        ]
        finder = SimpleShardedServiceFinder(SERVICE, source)
        finder.refresh()

        nodes = finder.get_all_nodes(criteria=lambda data: data["shardId"] == 1)

        assert [n.get_host() for n in nodes] == ["h1"]

    def test_no_criteria_returns_every_healthy_node_across_shards(self):
        source = mock.Mock()
        source.nodes.return_value = [_node("h1", {"shardId": 1}), _node("h2", {"shardId": 2})]
        finder = SimpleShardedServiceFinder(SERVICE, source)
        finder.refresh()

        assert sorted(n.get_host() for n in finder.get_all_nodes()) == ["h1", "h2"]
