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
from servicefinder.criteria import Criteria
from servicefinder.serviceregistry import ListBasedServiceRegistry, MapBasedServiceRegistry
from servicefinder.shardselector import ListShardSelector, MatchingShardSelector, NoopShardSelector, matches

SERVICE = Service("ns", "svc")


def _node(host, node_data=None, healthcheck_status=None):
    kwargs = {}
    if healthcheck_status is not None:
        kwargs["healthcheck_status"] = healthcheck_status
    return ServiceNode(host, 8080, node_data=node_data, **kwargs)


class _HostIsCriteria(Criteria):
    """A legacy-style Criteria that filters on the whole ServiceNode, not just node_data."""

    def __init__(self, host):
        self._host = host

    def filter(self, node):
        return node.get_host() == self._host


class TestMatchesAdapter:
    def test_none_criteria_matches_everything(self):
        assert matches(None, _node("h1")) is True

    def test_plain_callable_receives_node_data(self):
        seen = []

        def criteria(node_data):
            seen.append(node_data)
            return True

        matches(criteria, _node("h1", {"shardId": 1}))

        assert seen == [{"shardId": 1}]

    def test_legacy_criteria_receives_the_whole_node(self):
        assert matches(_HostIsCriteria("h1"), _node("h1")) is True
        assert matches(_HostIsCriteria("h1"), _node("h2")) is False


class TestNoopShardSelector:
    def test_returns_every_node_ignoring_criteria(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1"), _node("h2")])

        nodes = NoopShardSelector().nodes(lambda _: False, registry)

        assert sorted(n.get_host() for n in nodes) == ["h1", "h2"]


class TestListShardSelector:
    def test_none_criteria_returns_everything(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1"), _node("h2")])

        assert len(ListShardSelector().nodes(None, registry)) == 2

    def test_plain_predicate_filters_by_node_data(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1}), _node("h2", {"shardId": 2})])

        nodes = ListShardSelector().nodes(lambda data: data["shardId"] == 2, registry)

        assert [n.get_host() for n in nodes] == ["h2"]

    def test_legacy_criteria_is_honoured(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1"), _node("h2")])

        nodes = ListShardSelector().nodes(_HostIsCriteria("h2"), registry)

        assert [n.get_host() for n in nodes] == ["h2"]

    def test_no_match_returns_empty(self):
        registry = ListBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1})])

        assert ListShardSelector().nodes(lambda data: data["shardId"] == 99, registry) == []


class TestMatchingShardSelector:
    def test_none_criteria_returns_everything(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1}), _node("h2", {"shardId": 2})])

        assert len(MatchingShardSelector().nodes(None, registry)) == 2

    def test_predicate_is_evaluated_per_bucket(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([
            _node("h1", {"shardId": 1}),
            _node("h2", {"shardId": 1}),
            _node("h3", {"shardId": 2}),
        ])

        nodes = MatchingShardSelector().nodes(lambda data: data["shardId"] == 1, registry)

        assert sorted(n.get_host() for n in nodes) == ["h1", "h2"]

    def test_legacy_criteria_scans_individual_nodes(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1}), _node("h2", {"shardId": 1})])

        nodes = MatchingShardSelector().nodes(_HostIsCriteria("h2"), registry)

        assert [n.get_host() for n in nodes] == ["h2"]

    def test_no_matching_bucket_returns_empty(self):
        registry = MapBasedServiceRegistry(SERVICE)
        registry.update([_node("h1", {"shardId": 1})])

        assert MatchingShardSelector().nodes(lambda data: data["shardId"] == 99, registry) == []
