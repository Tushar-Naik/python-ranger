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

from rangermodels.ranger_models import Service, ServiceNode, ShardInfo
from servicefinder.serviceregistry import MapBasedServiceRegistry
from servicefinder.shardselector import HierarchicalEnvironmentAwareShardSelector, _environment_chain

SERVICE = Service("ns", "svc")


def _node(host, environment, region=None, tags=None):
    return ServiceNode(host, 8080, node_data=ShardInfo(environment=environment, region=region, tags=tags))


def _registry(*nodes):
    registry = MapBasedServiceRegistry(SERVICE)
    registry.update(list(nodes))
    return registry


class TestEnvironmentChain:
    def test_most_specific_first(self):
        assert list(_environment_chain("prod.region2.cell5", ".")) == [
            "prod.region2.cell5", "prod.region2", "prod",
        ]

    def test_single_segment_yields_itself_only(self):
        assert list(_environment_chain("prod", ".")) == ["prod"]

    def test_empty_string_yields_nothing(self):
        assert list(_environment_chain("", ".")) == []

    def test_custom_separator(self):
        assert list(_environment_chain("prod/region2", "/")) == ["prod/region2", "prod"]


class TestHierarchicalEnvironmentAwareShardSelector:
    def test_exact_match_wins(self):
        registry = _registry(
            _node("h1", "prod.region2.cell5"),
            _node("h2", "prod.region2"),
            _node("h3", "prod"),
        )
        selector = HierarchicalEnvironmentAwareShardSelector("prod.region2.cell5")

        nodes = selector.nodes(None, registry)

        assert [n.get_host() for n in nodes] == ["h1"]

    def test_falls_back_to_the_parent_environment(self):
        registry = _registry(_node("h2", "prod.region2"), _node("h3", "prod"))
        selector = HierarchicalEnvironmentAwareShardSelector("prod.region2.cell5")

        nodes = selector.nodes(None, registry)

        assert [n.get_host() for n in nodes] == ["h2"]

    def test_falls_back_all_the_way_to_the_root(self):
        registry = _registry(_node("h3", "prod"))
        selector = HierarchicalEnvironmentAwareShardSelector("prod.region2.cell5")

        nodes = selector.nodes(None, registry)

        assert [n.get_host() for n in nodes] == ["h3"]

    def test_no_match_anywhere_returns_empty(self):
        registry = _registry(_node("h1", "stage"))
        selector = HierarchicalEnvironmentAwareShardSelector("prod.region2.cell5")

        assert selector.nodes(None, registry) == []

    def test_environments_are_not_merged_across_tiers(self):
        registry = _registry(
            _node("h1", "prod.region2.cell5"),
            _node("h2", "prod.region2"),
        )
        selector = HierarchicalEnvironmentAwareShardSelector("prod.region2.cell5")

        nodes = selector.nodes(None, registry)

        # only the most specific tier's node, not both
        assert [n.get_host() for n in nodes] == ["h1"]

    def test_custom_separator(self):
        registry = _registry(_node("h1", "prod/region2"), _node("h2", "prod"))
        selector = HierarchicalEnvironmentAwareShardSelector("prod/region2/cell5", separator="/")

        nodes = selector.nodes(None, registry)

        assert [n.get_host() for n in nodes] == ["h1"]

    def test_criteria_is_applied_within_the_winning_tier(self):
        registry = _registry(
            _node("h1", "prod", region="r1"),
            _node("h2", "prod", region="r2"),
        )
        selector = HierarchicalEnvironmentAwareShardSelector("prod")

        nodes = selector.nodes(lambda shard: shard.region == "r2", registry)

        assert [n.get_host() for n in nodes] == ["h2"]

    def test_criteria_can_exclude_an_entire_tier_causing_further_fallback(self):
        registry = _registry(
            _node("h1", "prod.region2", region="only-in-region2"),
            _node("h2", "prod", region="fallback"),
        )
        selector = HierarchicalEnvironmentAwareShardSelector("prod.region2")

        nodes = selector.nodes(lambda shard: shard.region == "fallback", registry)

        assert [n.get_host() for n in nodes] == ["h2"]
