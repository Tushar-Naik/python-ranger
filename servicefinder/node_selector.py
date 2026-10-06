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
import threading
from abc import abstractmethod

from common.helper import is_empty

# the round robin cursor is kept monotonic (rather than being reduced against the
# current node count) so that changes in the node list do not reset the rotation.
# it is wrapped at this bound purely to keep the counter from growing without end.
_ROUND_ROBIN_COUNTER_BOUND = 1 << 31


class Selector(object):
    """
    class that is used to select one node from a list of ServiceNodes
    """

    @abstractmethod
    def select(self, node_list: list):
        """
        :param node_list: list of healthy ServiceNodes to select from
        :return: one item from the list
        """
        pass


class RandomNodeSelector(Selector):
    def select(self, node_list):
        """
        select one item from the list at random
        """
        if is_empty(node_list):
            return None
        return node_list[random.randint(0, len(node_list) - 1)]


class RoundRobinNodeSelector(Selector):
    def __init__(self):
        super().__init__()
        self.robin = 0
        self._lock = threading.Lock()

    def select(self, node_list):
        """
        selects items from the list in order
        """
        if is_empty(node_list):
            return None
        with self._lock:
            # read the current position first, then advance; incrementing before
            # indexing would make the very first call skip index 0
            index = self.robin % len(node_list)
            self.robin = (self.robin + 1) % _ROUND_ROBIN_COUNTER_BOUND
        return node_list[index]
