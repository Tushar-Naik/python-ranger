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

from unittest import mock

import pytest
import requests

from rangermodels.ranger_models import UrlScheme
from serviceprovider.health_check import HealthCheck, _NoHealthCheck

URL = "http://localhost:8080/healthcheck"


def _response(status_code):
    resp = mock.Mock()
    resp.status_code = status_code
    return resp


class TestHealthCheckStatusMapping:
    @pytest.mark.parametrize("status_code", [200, 201, 204, 299])
    def test_2xx_is_healthy(self, status_code):
        with mock.patch("requests.get", return_value=_response(status_code)):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is True

    @pytest.mark.parametrize("status_code", [301, 404, 500, 503])
    def test_non_2xx_is_unhealthy(self, status_code):
        with mock.patch("requests.get", return_value=_response(status_code)):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is False

    def test_acceptable_errors_are_treated_as_healthy(self):
        with mock.patch("requests.get", return_value=_response(503)):
            health_check = HealthCheck(URL, UrlScheme.GET, acceptable_errors=[503])
            assert health_check.is_healthy() is True

    def test_post_scheme_is_supported(self):
        with mock.patch("requests.post", return_value=_response(200)) as post:
            assert HealthCheck(URL, UrlScheme.POST, data="{}").is_healthy() is True
        assert post.call_args.kwargs["data"] == "{}"


class TestHealthCheckFailurePaths:
    """
    Regression tests: the transport error handlers logged and fell through, so
    is_healthy() returned None instead of False. None is falsy but is not a valid
    answer to a boolean health question, and it broke identity checks on the result.
    """

    def test_connection_error_reports_unhealthy(self):
        with mock.patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is False

    def test_read_timeout_reports_unhealthy(self):
        with mock.patch("requests.get", side_effect=requests.exceptions.ReadTimeout()):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is False

    def test_connect_timeout_reports_unhealthy(self):
        with mock.patch("requests.get", side_effect=requests.exceptions.ConnectTimeout()):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is False

    def test_generic_timeout_reports_unhealthy(self):
        with mock.patch("requests.get", side_effect=requests.exceptions.Timeout()):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is False

    def test_unexpected_error_reports_unhealthy(self):
        with mock.patch("requests.get", side_effect=ValueError("boom")):
            assert HealthCheck(URL, UrlScheme.GET).is_healthy() is False

    def test_invalid_scheme_reports_unhealthy(self):
        assert HealthCheck(URL, scheme="not-a-scheme").is_healthy() is False


class TestNoHealthCheck:
    def test_always_healthy(self):
        assert _NoHealthCheck(logger=None).is_healthy() is True
