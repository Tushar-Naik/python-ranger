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

import logging
import threading
import time

import pytest

from common import helper
from common.helper import get_default_logger

LOGGER_NAME = 'python-ranger'


@pytest.fixture
def clean_logger():
    """
    gives the test a ``python-ranger`` logger without handlers, and restores the
    original handlers/level afterwards so other tests are not affected.
    """
    logger = logging.getLogger(LOGGER_NAME)
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    logger.handlers = []
    yield logger
    logger.handlers = saved_handlers
    logger.setLevel(saved_level)


class TestGetDefaultLogger:
    def test_repeated_calls_attach_a_single_handler(self, clean_logger):
        for _ in range(5):
            get_default_logger()
        assert len(clean_logger.handlers) == 1

    def test_returns_the_shared_named_logger(self, clean_logger):
        assert get_default_logger() is clean_logger

    def test_concurrent_first_use_attaches_a_single_handler(self, clean_logger, monkeypatch):
        """
        Regression test: the "no handler yet?" check and ``addHandler`` were not
        guarded by one lock, so threads racing on first use could each observe an
        empty handler list and each attach a handler (every line logged N times).

        Handler construction is slowed down to widen the window between the check
        and the add, which makes the race fail deterministically without the lock.
        """
        real_stream_handler = logging.StreamHandler

        class SlowStreamHandler(real_stream_handler):
            def __init__(self, *args, **kwargs):
                time.sleep(0.05)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(helper.logging, 'StreamHandler', SlowStreamHandler)

        thread_count = 16
        barrier = threading.Barrier(thread_count)

        def first_use():
            barrier.wait()
            get_default_logger()

        threads = [threading.Thread(target=first_use) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(clean_logger.handlers) == 1
