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
import sys
import time


def current_milli_time():
    return round(time.time() * 1000)


def default_serialize_func(o):
    """
    Use like this: logging.debug(f"print this object: {json.dumps(myobject, indent=4, sort_keys=True, default=default_serialize_func)}")
    """
    if hasattr(o, '__dict__'):
        return o.__dict__
    return f"<could not serialize {o.__class__}>"


def get_default_logger():
    """
    :return: a logger named ``python-ranger`` writing to stdout.

    Idempotent: every caller without their own logger (ServiceNode sources/sinks,
    finders, providers...) ends up sharing this single named logger, so a handler
    is only ever attached once. Attaching one unconditionally on every call would
    pile up a new handler per instance, causing every log line to be printed once
    per instance ever constructed.
    """
    logger = logging.getLogger('python-ranger')
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    logger.setLevel(logging.INFO)
    return logger


def safe_get(mapping: dict, key, default=None):
    """
    :param mapping: dictionary of key values
    :param key: key being searched for
    :param default: default value in case key was not present in the dict
    :return: default value if the key is not present in the mapping dictionary, else the value in the dict for the key
    """
    if mapping is None or key not in mapping:
        return default
    return mapping[key]


def is_empty(val):
    """
    :param val: any iterable
    :return: true if it is empty
    """
    return val is None or len(val) == 0
