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

from rangermodels.ranger_models import Service, ServiceNode
from servicefinder.serviceregistry import ListBasedServiceRegistry, MapBasedServiceRegistry, _freeze

SERVICE = Service("ns", "svc")


def _node(host, node_data=None):
    return ServiceNode(host, 8080, node_data=node_data)


class TestFreeze:
    def test_equal_dicts_freeze_equal(self):
        assert _freeze({"a": 1, "b": [1, 2]}) == _freeze({"b": [1, 2], "a": 1})

    def test_different_dicts_freeze_different(self):
        assert _freeze({"a": 1}) != _freeze({"a": 2})

    def test_frozen_dict_is_hashable(self):
        hash(_freeze({"a": [1, {"b": 2}]}))  # must not raise

    def test_none_is_hashable(self):
        assert _freeze(None) is None

    def test_plain_scalars_pass_through(self):
        assert _freeze("shard-1") == "shard-1"
        assert _freeze(7) == 7


class TestListBasedServiceRegistry:
    def test_empty_registry_has_no_nodes(self):
        assert ListBasedServiceRegistry(SERVICE).node_list() == []

    def test_update_replaces_the_view(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1")])
        assert [n.get_host() for n in registry.node_list()] == ["h1"]
        registry.update([_node("h2"), _node("h3")])
        assert [n.get_host() for n in registry.node_list()] == ["h2", "h3"]

    def test_node_list_is_a_snapshot_not_a_live_view(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1")])
        snapshot = registry.node_list()
        registry.update([_node("h2")])
        assert [n.get_host() for n in snapshot] == ["h1"]


class TestMapBasedServiceRegistry:
    def test_buckets_by_node_data(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([
            _node("h1", {"shardId": 1}),
            _node("h2", {"shardId": 1}),
            _node("h3", {"shardId": 2}),
        ])

        shard1 = registry.nodes_for({"shardId": 1})
        shard2 = registry.nodes_for({"shardId": 2})

        assert sorted(n.get_host() for n in shard1) == ["h1", "h2"]
        assert [n.get_host() for n in shard2] == ["h3"]

    def test_unknown_shard_returns_empty(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1})])

        assert registry.nodes_for({"shardId": 99}) == []

    def test_node_list_returns_every_node_regardless_of_bucket(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1}), _node("h2", {"shardId": 2})])

        assert sorted(n.get_host() for n in registry.node_list()) == ["h1", "h2"]

    def test_nodes_exposes_the_full_bucket_mapping(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1}), _node("h2", {"shardId": 2})])

        assert len(registry.nodes()) == 2

    def test_update_replaces_previous_buckets(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1})])
        registry.update([_node("h2", {"shardId": 2})])

        assert registry.nodes_for({"shardId": 1}) == []
        assert [n.get_host() for n in registry.nodes_for({"shardId": 2})] == ["h2"]
