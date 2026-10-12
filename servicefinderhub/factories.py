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
Convenience factories wiring a shared :class:`~transport.base.NodeDataSource`
into the finder flavors from :mod:`servicefinder.simple_finder`, for use as a
:class:`~servicefinderhub.finder_hub.ServiceFinderHub`'s ``finder_factory``.

The same source instance is reused across every service the hub discovers
(it is also the source the hub itself uses for ``services()``), rather than
opening a new connection per service.
"""

from servicefinder.simple_finder import SimpleShardedServiceFinder, SimpleUnshardedServiceFinder
from transport.base import NodeDataSource


def unsharded_finder_factory(source: NodeDataSource, selector=None, logger=None,
                             zombie_check_threshold_time_in_ms=60000):
    """
    :param source: shared NodeDataSource, typically the same one the hub uses for discovery
    :return: a finder_factory, ``callable(Service) -> SimpleUnshardedServiceFinder``
    """
    def build(service):
        return SimpleUnshardedServiceFinder(service, source, selector=selector, logger=logger,
                                            zombie_check_threshold_time_in_ms=zombie_check_threshold_time_in_ms)
    return build


def sharded_finder_factory(source: NodeDataSource, selector=None, logger=None,
                           zombie_check_threshold_time_in_ms=60000):
    """
    :param source: shared NodeDataSource, typically the same one the hub uses for discovery
    :return: a finder_factory, ``callable(Service) -> SimpleShardedServiceFinder``
    """
    def build(service):
        return SimpleShardedServiceFinder(service, source, selector=selector, logger=logger,
                                          zombie_check_threshold_time_in_ms=zombie_check_threshold_time_in_ms)
    return build
