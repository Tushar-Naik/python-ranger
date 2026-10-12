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

import time
from unittest import mock

from common.helper import current_milli_time
from rangermodels.ranger_models import Service, ServiceNode
from servicefinderhub.factories import unsharded_finder_factory
from servicefinderhub.finder_hub import ServiceFinderHub

NS = "ns"
SVC_A = Service(NS, "a")
SVC_B = Service(NS, "b")


def _fresh_node(host):
    return ServiceNode(host, 8080, last_updated_timestamp=current_milli_time())


def _source(services=(), nodes_by_service=None):
    source = mock.Mock()
    source.services.return_value = set(services)
    nodes_by_service = nodes_by_service or {}
    source.nodes.side_effect = lambda service: nodes_by_service.get(service, [])
    return source


class TestServiceDiscovery:
    def test_start_builds_a_finder_per_discovered_service(self):
        source = _source(services=[SVC_A, SVC_B])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))

        hub.start()

        assert hub.services() == {SVC_A, SVC_B}
        assert hub.finder(SVC_A) is not None
        assert hub.finder(SVC_B) is not None
        hub.stop()

    def test_an_unknown_service_has_no_finder(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))
        hub.start()

        assert hub.finder(SVC_B) is None
        hub.stop()

    def test_a_newly_appeared_service_gets_a_finder_on_the_next_refresh(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source), refresh_interval_ms=10**9)
        hub.start()
        assert hub.finder(SVC_B) is None

        source.services.return_value = {SVC_A, SVC_B}
        hub._refresh_once()

        assert hub.finder(SVC_B) is not None
        hub.stop()

    def test_a_vanished_service_loses_its_finder(self):
        source = _source(services=[SVC_A, SVC_B])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source), refresh_interval_ms=10**9)
        hub.start()
        assert hub.finder(SVC_B) is not None

        source.services.return_value = {SVC_A}
        hub._refresh_once()

        assert hub.finder(SVC_B) is None
        hub.stop()

    def test_an_excluded_service_never_gets_a_finder(self):
        source = _source(services=[SVC_A, SVC_B])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source), excluded_services={"b"})

        hub.start()

        assert hub.services() == {SVC_A}
        hub.stop()

    def test_a_single_bad_service_does_not_break_the_others(self):
        source = _source(services=[SVC_A, SVC_B])
        calls = []

        def factory(service):
            calls.append(service)
            if service == SVC_B:
                raise RuntimeError("boom")
            return unsharded_finder_factory(source)(service)

        hub = ServiceFinderHub(source, factory)
        hub.start()

        assert hub.finder(SVC_A) is not None
        assert hub.finder(SVC_B) is None
        hub.stop()

    def test_a_failed_catalogue_listing_does_not_raise(self):
        source = mock.Mock()
        source.services.side_effect = RuntimeError("boom")
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))

        hub.start()  # must not raise

        assert hub.services() == set()
        hub.stop()


class TestNodeRefresh:
    def test_discovered_finders_are_populated_with_nodes(self):
        node = _fresh_node("h1")
        source = _source(services=[SVC_A], nodes_by_service={SVC_A: [node]})
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))

        hub.start()

        assert [n.get_host() for n in hub.finder(SVC_A).get_all_nodes()] == ["h1"]
        hub.stop()

    def test_existing_finders_are_refreshed_on_every_tick(self):
        source = _source(services=[SVC_A], nodes_by_service={SVC_A: [_fresh_node("h1")]})
        hub = ServiceFinderHub(source, unsharded_finder_factory(source), refresh_interval_ms=10**9)
        hub.start()
        assert [n.get_host() for n in hub.finder(SVC_A).get_all_nodes()] == ["h1"]

        source.nodes.side_effect = lambda service: [_fresh_node("h2")]
        hub._refresh_once()

        assert [n.get_host() for n in hub.finder(SVC_A).get_all_nodes()] == ["h2"]
        hub.stop()


class TestLifecycle:
    def test_start_is_idempotent(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))
        hub.start()
        hub.start()
        source.start.assert_called_once()
        hub.stop()

    def test_stop_before_start_is_a_noop(self):
        source = _source()
        ServiceFinderHub(source, unsharded_finder_factory(source)).stop()

    def test_is_ready_only_after_the_first_refresh_attempt(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))
        assert hub.is_ready() is False

        hub.start()

        assert hub.is_ready() is True
        hub.stop()

    def test_start_is_not_blocked_by_a_failing_first_refresh(self):
        source = mock.Mock()
        source.services.side_effect = RuntimeError("boom")
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))

        started_at = time.monotonic()
        hub.start()
        elapsed = time.monotonic() - started_at

        assert elapsed < 1.0
        assert hub.is_ready() is True
        hub.stop()

    def test_stop_stops_the_source(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))
        hub.start()

        hub.stop()

        source.stop.assert_called_once()

    def test_background_refresh_runs_on_the_configured_interval(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source), refresh_interval_ms=20)
        hub.start()
        calls_at_start = source.services.call_count

        time.sleep(0.1)

        assert source.services.call_count > calls_at_start
        hub.stop()

    def test_update_listener_is_invoked_after_refresh(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))
        seen = []
        hub.register_update_listener(lambda: seen.append(1))

        hub.start()

        assert seen == [1]
        hub.stop()

    def test_a_raising_listener_does_not_break_the_refresh(self):
        source = _source(services=[SVC_A])
        hub = ServiceFinderHub(source, unsharded_finder_factory(source))
        hub.register_update_listener(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        hub.start()  # must not raise

        assert hub.services() == {SVC_A}
        hub.stop()
