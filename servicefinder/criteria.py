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

from abc import abstractmethod

from rangermodels.ranger_models import ServiceNode


class Criteria(object):
    """
    A filter criteria while selecting service nodes
    """

    @abstractmethod
    def filter(self, node: ServiceNode):
        """
        :param node: service node
        :return: true if the node is supposed to be used when the selector algorithm runs, false if it needs to
        be filtered out and excluded
        """
        pass
