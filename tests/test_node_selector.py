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

import threading

from servicefinder.node_selector import RandomNodeSelector, RoundRobinNodeSelector


class TestRoundRobinNodeSelector:
    def test_first_selection_is_the_first_node(self):
        """
        Regression test: the cursor used to be incremented before indexing, so the
        first element of the list was skipped on the first call.
        """
        assert RoundRobinNodeSelector().select(["a", "b", "c"]) == "a"

    def test_rotates_in_order_starting_from_the_head(self):
        selector = RoundRobinNodeSelector()
        picked = [selector.select(["a", "b", "c"]) for _ in range(6)]
        assert picked == ["a", "b", "c", "a", "b", "c"]

    def test_single_node_list_always_returns_that_node(self):
        selector = RoundRobinNodeSelector()
        assert [selector.select(["only"]) for _ in range(3)] == ["only"] * 3

    def test_empty_or_none_list_returns_none(self):
        selector = RoundRobinNodeSelector()
        assert selector.select([]) is None
        assert selector.select(None) is None

    def test_rotation_is_not_reset_by_a_changing_node_count(self):
        selector = RoundRobinNodeSelector()
        assert selector.select(["a", "b", "c"]) == "a"
        assert selector.select(["a", "b"]) == "b"
        assert selector.select(["a", "b", "c"]) == "c"

    def test_concurrent_selection_distributes_evenly(self):
        selector = RoundRobinNodeSelector()
        nodes = ["a", "b", "c", "d"]
        counts = {node: 0 for node in nodes}
        lock = threading.Lock()

        def pick():
            for _ in range(250):
                chosen = selector.select(nodes)
                with lock:
                    counts[chosen] += 1

        threads = [threading.Thread(target=pick) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(counts.values()) == 1000
        assert all(count == 250 for count in counts.values())


class TestRandomNodeSelector:
    def test_returns_a_member_of_the_list(self):
        selector = RandomNodeSelector()
        nodes = ["a", "b", "c"]
        assert all(selector.select(nodes) in nodes for _ in range(50))

    def test_can_return_the_first_node(self):
        selector = RandomNodeSelector()
        assert any(selector.select(["a", "b", "c"]) == "a" for _ in range(200))

    def test_empty_or_none_list_returns_none(self):
        selector = RandomNodeSelector()
        assert selector.select([]) is None
        assert selector.select(None) is None
