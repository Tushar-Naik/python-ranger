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
Weighted, warmup-aware node selection.

``RandomNodeSelector`` and ``RoundRobinNodeSelector`` treat every node alike.
That is a poor fit right after a deploy or a restart: a node that has only just
turned healthy is typically cold (empty caches, unwarmed connection pools, a JIT
that has not kicked in) and is easily overwhelmed if it immediately receives the
same share of traffic as nodes that have been serving for hours.

Two fields published with every node make a smoother ramp possible:

* ``routingWeight`` -- an explicit relative weight chosen by the service owner
* ``healthySinceTimeStamp`` -- when the node most recently became healthy

:class:`WeightedRandomServiceNodeSelector` turns those into a selection
probability. It mirrors the weighted selection of the reference implementation
(``appform-io/ranger``, ``ranger-core`` ``finder/nodeselector``):

* every node's weight is the product of a list of :class:`WeightEnricher` outputs
* up to ``weighted_selection_threshold`` nodes the pick is an exact weighted random
  draw (:class:`IterativeWeightedSelector`, O(n))
* above it the cheaper "power of two choices" is used instead
  (:class:`TwoNodeComparisonWeightedSelector`, O(1)), which still favours heavier
  nodes without paying for a full pass over a large node list on every request

All selectors implement :class:`servicefinder.node_selector.Selector`, so they can
be passed anywhere a ``RandomNodeSelector`` can.
"""

import bisect
import random
from abc import ABC, abstractmethod

from common.helper import current_milli_time, is_empty
from servicefinder.node_selector import Selector

DEFAULT_MIN_NODE_AGE_MS = 60000
DEFAULT_BOOST_FACTOR = 1.0
DEFAULT_WEIGHTED_SELECTION_MIN_NODES_THRESHOLD = 10

MAX_MIN_NODE_AGE_MS = 600000
MIN_BOOST_FACTOR = 1.0
MAX_BOOST_FACTOR = 5.0
MIN_WEIGHTED_SELECTION_THRESHOLD = 1
MAX_WEIGHTED_SELECTION_THRESHOLD = 50


class WeightedNodeSelectorConfig(object):
    """
    Tunables for :class:`WeightedRandomServiceNodeSelector`. Defaults and valid
    ranges are the reference implementation's.
    """

    def __init__(self,
                 min_node_age_ms: int = DEFAULT_MIN_NODE_AGE_MS,
                 weight_boost_multiplier: float = DEFAULT_BOOST_FACTOR,
                 weighted_selection_threshold: int = DEFAULT_WEIGHTED_SELECTION_MIN_NODES_THRESHOLD):
        """
        :param min_node_age_ms: a node healthy for longer than this is considered
          warmed up and has its weight boosted. 0 to 600000.
        :param weight_boost_multiplier: factor applied to the weight of warmed up
          nodes. 1.0 (no boost) to 5.0.
        :param weighted_selection_threshold: node count up to which the exact
          weighted draw is used, above which the cheaper two node comparison takes over.
          1 to 50.
        """
        self.min_node_age_ms = min_node_age_ms
        self.weight_boost_multiplier = weight_boost_multiplier
        self.weighted_selection_threshold = weighted_selection_threshold

    def validate(self):
        if self.min_node_age_ms < 0 or self.min_node_age_ms > MAX_MIN_NODE_AGE_MS:
            raise ValueError(f"min_node_age_ms must be between 0 and {MAX_MIN_NODE_AGE_MS}")
        if self.weight_boost_multiplier < MIN_BOOST_FACTOR or self.weight_boost_multiplier > MAX_BOOST_FACTOR:
            raise ValueError(f"weight_boost_multiplier must be between {MIN_BOOST_FACTOR} and {MAX_BOOST_FACTOR}")
        if (self.weighted_selection_threshold < MIN_WEIGHTED_SELECTION_THRESHOLD
                or self.weighted_selection_threshold > MAX_WEIGHTED_SELECTION_THRESHOLD):
            raise ValueError(f"weighted_selection_threshold must be between {MIN_WEIGHTED_SELECTION_THRESHOLD} "
                             f"and {MAX_WEIGHTED_SELECTION_THRESHOLD}")

    def __repr__(self):
        return (f"WeightedNodeSelectorConfig(min_node_age_ms={self.min_node_age_ms}, "
                f"weight_boost_multiplier={self.weight_boost_multiplier}, "
                f"weighted_selection_threshold={self.weighted_selection_threshold})")


class WeightEnricher(ABC):
    """
    Computes one multiplicative factor of a node's selection weight.
    """

    @abstractmethod
    def enrich_weight(self, node):
        """
        :param node: the ServiceNode being weighed
        :return: a non-negative factor, 1.0 meaning "no adjustment"
        """


class RoutingWeightEnricher(WeightEnricher):
    """
    Contributes the weight the node published for itself.
    """

    def enrich_weight(self, node):
        return node.routing_weight


class TimeBasedWeightEnricher(WeightEnricher):
    """
    Boosts nodes that have been healthy for long enough to be considered warmed
    up, leaving recently healthy ones at the baseline. As established nodes get
    the boost, a freshly started one receives proportionally less traffic until
    it has aged in, instead of an equal share the instant it turns healthy.
    """

    def __init__(self, min_node_age_ms: int, weight_boost_multiplier: float, clock=current_milli_time):
        """
        :param min_node_age_ms: healthy duration after which a node counts as warmed up
        :param weight_boost_multiplier: factor returned for a warmed up node
        :param clock: ``callable() -> epoch millis``; injectable for tests
        """
        self.min_node_age_ms = min_node_age_ms
        self.weight_boost_multiplier = weight_boost_multiplier
        self._clock = clock

    def enrich_weight(self, node):
        if (self._clock() - node.healthy_since_timestamp) > self.min_node_age_ms:
            return self.weight_boost_multiplier
        return 1.0


class AbstractWeightedSelector(Selector):
    """
    Base for selectors driven by a list of :class:`WeightEnricher`. A node's
    weight is the product of every enricher's factor.
    """

    def __init__(self, weight_enrichers, rng=None):
        """
        :param weight_enrichers: list of WeightEnricher
        :param rng: source of randomness, anything with ``random()`` and ``sample()``.
          Defaults to the ``random`` module; injectable for deterministic tests.
        """
        self._weight_enrichers = list(weight_enrichers)
        self._rng = rng if rng is not None else random

    def adjust_weight(self, node):
        adjusted_weight = 1.0
        for enricher in self._weight_enrichers:
            adjusted_weight *= enricher.enrich_weight(node)
        return adjusted_weight

    @abstractmethod
    def select(self, node_list):
        """
        :return: one node, or None for an empty list
        """


class IterativeWeightedSelector(AbstractWeightedSelector):
    """
    Exact weighted random selection: probability of a node is its weight over the
    total weight. Costs a pass over the node list per pick.
    """

    def select(self, node_list):
        if is_empty(node_list):
            return None

        cumulative_weights = []
        total_weight = 0.0
        for node in node_list:
            total_weight += max(self.adjust_weight(node), 0.0)
            cumulative_weights.append(total_weight)

        if total_weight <= 0.0:
            # every node is weighted out (all published a weight of 0): there is no
            # meaningful proportion to honour, so spread uniformly rather than fail
            return node_list[self._rng.sample(range(len(node_list)), 1)[0]]

        random_value = self._rng.random() * total_weight
        # first node whose cumulative weight exceeds the draw. bisect_right (not
        # _left) so that a zero weight node, whose cumulative weight equals its
        # predecessor's, can never be picked.
        index = bisect.bisect_right(cumulative_weights, random_value)
        return node_list[min(index, len(node_list) - 1)]


class TwoNodeComparisonWeightedSelector(AbstractWeightedSelector):
    """
    "Power of two choices": draw two distinct nodes uniformly and keep the heavier.
    O(1) per pick, and still skews towards heavier nodes, at the cost of not being
    exactly proportional to weight.
    """

    def select(self, node_list):
        if is_empty(node_list):
            return None
        if len(node_list) == 1:
            return node_list[0]

        first_index, second_index = self._rng.sample(range(len(node_list)), 2)
        first, second = node_list[first_index], node_list[second_index]
        # strictly greater to keep the first, ties go to the second (as the reference does)
        return first if self.adjust_weight(first) > self.adjust_weight(second) else second


class ConditionalNodeSelector(Selector):
    """
    Chooses between two selectors depending on a condition over the node list.
    """

    def __init__(self, condition, primary_selector: Selector, secondary_selector: Selector):
        """
        :param condition: ``callable(node_list) -> bool``; when true the primary
          selector is used, otherwise the secondary
        """
        self._condition = condition
        self._primary_selector = primary_selector
        self._secondary_selector = secondary_selector

    def select(self, node_list):
        if is_empty(node_list):
            return None
        if self._condition(node_list):
            return self._primary_selector.select(node_list)
        return self._secondary_selector.select(node_list)


class WeightedRandomServiceNodeSelector(Selector):
    """
    Warmup-aware weighted selection. Combines each node's published
    ``routing_weight`` with a time based boost for nodes that have been healthy
    long enough, picking exactly (proportional to weight) for small node lists and
    by two node comparison for large ones.
    """

    def __init__(self, config: WeightedNodeSelectorConfig = None, rng=None, clock=current_milli_time):
        """
        :param config: tunables, defaults to :class:`WeightedNodeSelectorConfig` defaults
        :param rng: see :class:`AbstractWeightedSelector`
        :param clock: ``callable() -> epoch millis`` used for node age; injectable for tests
        """
        config = config if config is not None else WeightedNodeSelectorConfig()
        config.validate()
        self.config = config

        enrichers = [
            RoutingWeightEnricher(),
            TimeBasedWeightEnricher(config.min_node_age_ms, config.weight_boost_multiplier, clock=clock),
        ]
        self._conditional_selector = ConditionalNodeSelector(
            lambda nodes: len(nodes) <= config.weighted_selection_threshold,
            IterativeWeightedSelector(enrichers, rng=rng),
            TwoNodeComparisonWeightedSelector(enrichers, rng=rng))

    def select(self, node_list):
        return self._conditional_selector.select(node_list)
