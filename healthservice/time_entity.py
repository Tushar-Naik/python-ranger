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
A simple initial-delay/interval/unit wrapper used to schedule a monitor's checks.
"""


class TimeEntity(object):
    def __init__(self, time_interval, time_unit_seconds=1.0, initial_delay=0):
        """
        :param time_interval: how often the check repeats, in units of ``time_unit_seconds``
        :param time_unit_seconds: seconds represented by one unit of time_interval
        (default 1.0, i.e. time_interval is already in seconds)
        :param initial_delay: delay, in the same units, before the first run
        """
        self.time_interval = time_interval
        self.time_unit_seconds = time_unit_seconds
        self.initial_delay = initial_delay

    def interval_seconds(self):
        return self.time_interval * self.time_unit_seconds

    def initial_delay_seconds(self):
        return self.initial_delay * self.time_unit_seconds

    @classmethod
    def every_second(cls):
        return cls(1, 1.0)

    @classmethod
    def every_minute(cls):
        return cls(1, 60.0)

    @classmethod
    def every_hour(cls):
        return cls(1, 3600.0)

    @classmethod
    def every_day(cls):
        return cls(1, 86400.0)

    def __repr__(self):
        return (f"TimeEntity(time_interval={self.time_interval}, time_unit_seconds={self.time_unit_seconds}, "
                f"initial_delay={self.initial_delay})")
