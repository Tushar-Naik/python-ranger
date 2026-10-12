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

import random
from collections import Counter
from unittest import mock

import pytest

from rangermodels.ranger_models import Service, ServiceNode
from servicefinder.node_selector import Selector
from servicefinder.simple_finder import SimpleUnshardedServiceFinder
from servicefinder.weighted_selector import (
    ConditionalNodeSelector,
    IterativeWeightedSelector,
    RoutingWeightEnricher,
    TimeBasedWeightEnricher,
    TwoNodeComparisonWeightedSelector,
    WeightedNodeSelectorConfig,
    WeightedRandomServiceNodeSelector,
)

NOW = 1_700_000_000_000


def _node(host, routing_weight=1.0, healthy_since=0):
    return ServiceNode(host, 8080, routing_weight=routing_weight, healthy_since_timestamp=healthy_since)


def _distribution(selector, nodes, draws=20000):
    counts = Counter(selector.select(nodes).get_host() for _ in range(draws))
    return {host: count / draws for host, count in counts.items()}


class TestWeightedNodeSelectorConfig:
    def test_defaults_match_the_reference_implementation(self):
        config = WeightedNodeSelectorConfig()
        assert config.min_node_age_ms == 60000
        assert config.weight_boost_multiplier == 1.0
        assert config.weighted_selection_threshold == 10

    def test_defaults_are_valid(self):
        WeightedNodeSelectorConfig().validate()

    @pytest.mark.parametrize("kwargs", [
        {"min_node_age_ms": -1},
        {"min_node_age_ms": 600001},
        {"weight_boost_multiplier": 0.99},
        {"weight_boost_multiplier": 5.01},
        {"weighted_selection_threshold": 0},
        {"weighted_selection_threshold": 51},
    ])
    def test_out_of_range_values_are_rejected(self, kwargs):
        with pytest.raises(ValueError):
            WeightedNodeSelectorConfig(**kwargs).validate()

    @pytest.mark.parametrize("kwargs", [
        {"min_node_age_ms": 0},
        {"min_node_age_ms": 600000},
        {"weight_boost_multiplier": 1.0},
        {"weight_boost_multiplier": 5.0},
        {"weighted_selection_threshold": 1},
        {"weighted_selection_threshold": 50},
    ])
    def test_boundary_values_are_accepted(self, kwargs):
        WeightedNodeSelectorConfig(**kwargs).validate()

    def test_the_selector_validates_its_config(self):
        with pytest.raises(ValueError):
            WeightedRandomServiceNodeSelector(WeightedNodeSelectorConfig(weight_boost_multiplier=9))


class TestEnrichers:
    def test_routing_weight_enricher_returns_the_published_weight(self):
        assert RoutingWeightEnricher().enrich_weight(_node("h", routing_weight=2.5)) == 2.5

    def test_an_aged_node_is_boosted(self):
        enricher = TimeBasedWeightEnricher(60000, 3.0, clock=lambda: NOW)
        assert enricher.enrich_weight(_node("h", healthy_since=NOW - 120000)) == 3.0

    def test_a_recently_healthy_node_stays_at_baseline(self):
        enricher = TimeBasedWeightEnricher(60000, 3.0, clock=lambda: NOW)
        assert enricher.enrich_weight(_node("h", healthy_since=NOW - 1000)) == 1.0

    def test_the_age_threshold_is_exclusive(self):
        enricher = TimeBasedWeightEnricher(60000, 3.0, clock=lambda: NOW)
        assert enricher.enrich_weight(_node("h", healthy_since=NOW - 60000)) == 1.0
        assert enricher.enrich_weight(_node("h", healthy_since=NOW - 60001)) == 3.0

    def test_a_node_that_never_published_healthy_since_counts_as_aged(self):
        # nodes from publishers predating the field carry the unset sentinel
        enricher = TimeBasedWeightEnricher(60000, 3.0, clock=lambda: NOW)
        assert enricher.enrich_weight(ServiceNode("h", 1)) == 3.0


class TestIterativeWeightedSelector:
    def test_selection_is_proportional_to_weight(self):
        selector = IterativeWeightedSelector([RoutingWeightEnricher()], rng=random.Random(7))
        distribution = _distribution(selector, [_node("light", 1.0), _node("heavy", 3.0)])

        assert distribution["heavy"] == pytest.approx(0.75, abs=0.02)
        assert distribution["light"] == pytest.approx(0.25, abs=0.02)

    def test_enrichers_compound_multiplicatively(self):
        enrichers = [RoutingWeightEnricher(), TimeBasedWeightEnricher(1000, 2.0, clock=lambda: NOW)]
        selector = IterativeWeightedSelector(enrichers, rng=random.Random(7))
        nodes = [_node("new", 1.0, healthy_since=NOW), _node("old", 1.0, healthy_since=NOW - 10000)]

        # new weighs 1*1, old weighs 1*2
        distribution = _distribution(selector, nodes)

        assert distribution["old"] == pytest.approx(2 / 3, abs=0.02)

    def test_a_zero_weight_node_is_never_selected(self):
        selector = IterativeWeightedSelector([RoutingWeightEnricher()], rng=random.Random(7))
        nodes = [_node("drained", 0.0), _node("live", 1.0), _node("also-drained", 0.0)]

        assert set(_distribution(selector, nodes, draws=5000)) == {"live"}

    def test_a_draw_landing_exactly_on_a_boundary_never_picks_a_zero_weight_node(self):
        # a draw of exactly 0.0 sits on the boundary of a leading zero weight node's
        # (empty) interval; it must go to the first node that actually has weight
        rng = mock.Mock()
        rng.random.return_value = 0.0
        selector = IterativeWeightedSelector([RoutingWeightEnricher()], rng=rng)

        assert selector.select([_node("drained", 0.0), _node("live", 1.0)]).get_host() == "live"

    def test_a_draw_on_an_interior_boundary_goes_to_the_following_interval(self):
        # weights 1,0,1 -> cumulative 1,1,2. A draw of exactly 1.0 belongs to [1, 2), the
        # last node, not to the first node's [0, 1) interval and not to the drained node
        rng = mock.Mock()
        rng.random.return_value = 0.5
        selector = IterativeWeightedSelector([RoutingWeightEnricher()], rng=rng)

        assert selector.select([_node("a", 1.0), _node("drained", 0.0), _node("b", 1.0)]).get_host() == "b"

    def test_all_zero_weights_fall_back_to_uniform(self):
        selector = IterativeWeightedSelector([RoutingWeightEnricher()], rng=random.Random(7))
        distribution = _distribution(selector, [_node("a", 0.0), _node("b", 0.0)], draws=10000)

        assert distribution["a"] == pytest.approx(0.5, abs=0.03)

    def test_a_negative_weight_is_treated_as_zero(self):
        selector = IterativeWeightedSelector([RoutingWeightEnricher()], rng=random.Random(7))

        assert set(_distribution(selector, [_node("bad", -5.0), _node("ok", 1.0)], draws=2000)) == {"ok"}

    def test_empty_list_returns_none(self):
        assert IterativeWeightedSelector([RoutingWeightEnricher()]).select([]) is None
        assert IterativeWeightedSelector([RoutingWeightEnricher()]).select(None) is None

    def test_single_node_is_always_selected(self):
        selector = IterativeWeightedSelector([RoutingWeightEnricher()])
        assert selector.select([_node("only")]).get_host() == "only"


class TestTwoNodeComparisonWeightedSelector:
    def test_the_heavier_of_the_two_drawn_nodes_wins(self):
        selector = TwoNodeComparisonWeightedSelector([RoutingWeightEnricher()], rng=random.Random(7))

        for _ in range(200):
            assert selector.select([_node("light", 1.0), _node("heavy", 9.0)]).get_host() == "heavy"

    def test_a_heavy_node_wins_whenever_it_is_one_of_the_drawn_pair(self):
        selector = TwoNodeComparisonWeightedSelector([RoutingWeightEnricher()], rng=random.Random(7))
        nodes = [_node("heavy", 10.0), _node("a", 1.0), _node("b", 1.0)]

        # with 3 nodes the heavy one is in the drawn pair 2 times out of 3
        assert _distribution(selector, nodes)["heavy"] == pytest.approx(2 / 3, abs=0.02)

    def test_ties_go_to_the_second_drawn_node(self):
        rng = mock.Mock()
        rng.sample.return_value = [0, 1]
        selector = TwoNodeComparisonWeightedSelector([RoutingWeightEnricher()], rng=rng)

        assert selector.select([_node("first", 1.0), _node("second", 1.0)]).get_host() == "second"

    def test_single_node_is_returned_without_drawing(self):
        rng = mock.Mock()
        selector = TwoNodeComparisonWeightedSelector([RoutingWeightEnricher()], rng=rng)

        assert selector.select([_node("only")]).get_host() == "only"
        rng.sample.assert_not_called()

    def test_empty_list_returns_none(self):
        assert TwoNodeComparisonWeightedSelector([RoutingWeightEnricher()]).select([]) is None


class _Fixed(Selector):
    def __init__(self, label):
        self.label = label

    def select(self, node_list):
        return self.label


class TestConditionalNodeSelector:
    def test_uses_the_primary_when_the_condition_holds(self):
        selector = ConditionalNodeSelector(lambda nodes: len(nodes) < 3, _Fixed("primary"), _Fixed("secondary"))
        assert selector.select([_node("a")]) == "primary"

    def test_uses_the_secondary_otherwise(self):
        selector = ConditionalNodeSelector(lambda nodes: len(nodes) < 3, _Fixed("primary"), _Fixed("secondary"))
        assert selector.select([_node("a"), _node("b"), _node("c")]) == "secondary"

    def test_empty_list_returns_none_without_evaluating_the_condition(self):
        condition = mock.Mock()
        assert ConditionalNodeSelector(condition, _Fixed("p"), _Fixed("s")).select([]) is None
        condition.assert_not_called()


class TestWeightedRandomServiceNodeSelector:
    def _selector(self, threshold=10, boost=2.0, rng_seed=7):
        config = WeightedNodeSelectorConfig(min_node_age_ms=60000, weight_boost_multiplier=boost,
                                            weighted_selection_threshold=threshold)
        return WeightedRandomServiceNodeSelector(config, rng=random.Random(rng_seed), clock=lambda: NOW)

    def test_a_freshly_healthy_node_receives_less_traffic_than_an_aged_one(self):
        nodes = [_node("fresh", healthy_since=NOW - 1000), _node("aged", healthy_since=NOW - 600000)]

        distribution = _distribution(self._selector(boost=3.0), nodes)

        # fresh weighs 1, aged weighs 3
        assert distribution["fresh"] == pytest.approx(0.25, abs=0.02)

    def test_with_no_boost_configured_aged_and_fresh_nodes_are_equal(self):
        nodes = [_node("fresh", healthy_since=NOW - 1000), _node("aged", healthy_since=NOW - 600000)]

        assert _distribution(self._selector(boost=1.0), nodes)["fresh"] == pytest.approx(0.5, abs=0.02)

    def test_routing_weight_still_applies_on_top_of_the_warmup_boost(self):
        nodes = [_node("a", routing_weight=1.0, healthy_since=NOW - 600000),
                 _node("b", routing_weight=3.0, healthy_since=NOW - 600000)]

        assert _distribution(self._selector(boost=2.0), nodes)["b"] == pytest.approx(0.75, abs=0.02)

    def test_at_or_below_the_threshold_the_exact_selector_is_used(self):
        # exact selection of [1, 3] gives 75%; two node comparison of a pair always picks the heavier (100%)
        nodes = [_node("light", 1.0, healthy_since=NOW), _node("heavy", 3.0, healthy_since=NOW)]

        distribution = _distribution(self._selector(threshold=2, boost=1.0), nodes)

        assert distribution["light"] == pytest.approx(0.25, abs=0.02)

    def test_above_the_threshold_two_node_comparison_is_used(self):
        nodes = [_node("light", 1.0, healthy_since=NOW), _node("heavy", 3.0, healthy_since=NOW)]

        distribution = _distribution(self._selector(threshold=1, boost=1.0), nodes, draws=2000)

        assert set(distribution) == {"heavy"}

    def test_empty_list_returns_none(self):
        assert self._selector().select([]) is None

    def test_default_construction(self):
        node = WeightedRandomServiceNodeSelector().select([_node("only")])
        assert node.get_host() == "only"


class TestUsableAsAFinderSelector:
    def test_drops_into_a_finder_like_any_other_selector(self):
        from common.helper import current_milli_time
        source = mock.Mock()
        source.nodes.return_value = [
            ServiceNode("h1", 8080, last_updated_timestamp=current_milli_time(), routing_weight=1.0),
            ServiceNode("h2", 8080, last_updated_timestamp=current_milli_time(), routing_weight=1.0),
        ]
        finder = SimpleUnshardedServiceFinder(Service("ns", "svc"), source,
                                              selector=WeightedRandomServiceNodeSelector())
        finder.refresh()

        assert finder.get_node().get_host() in {"h1", "h2"}
