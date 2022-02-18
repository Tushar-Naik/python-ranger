import requests

from serviceprovider.ranger_models import UrlScheme
from serviceprovider.helper import get_default_logger


class HealthCheck(object):
    def __init__(self, url, scheme: UrlScheme, logger=None, data=None, headers=None, timeout=1.0, acceptable_errors=None):
        """
        :param url: url path where health pings can be done at
        :param scheme: GET / POST
        :param logger: custom logger if provided
        :param data: data if its a POST scheme
        :param headers: headers if required
        :param timeout: timeout for the ping call
        :param acceptable_errors: in case you wanna indicate that some non-2xx response is acceptable
        """
        self.url = url
        self.scheme = scheme
        self.logger = logger if logger is not None else get_default_logger()
        self.data = data
        self.timeout = timeout
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self.acceptable_errors = acceptable_errors if acceptable_errors is not None else []

    def is_healthy(self):
        try:
            if UrlScheme.GET == self.scheme:
                resp = requests.get(url=self.url, headers=self.headers, timeout=self.timeout)
                self.logger.info(f"Checking health at:{self.url}, URL returned:{resp.status_code}")
                return self._check_status(resp)
            elif UrlScheme.POST == self.scheme:
                resp = requests.post(url=self.url, headers=self.headers, timeout=self.timeout, data=self.data)
                self.logger.info(f"Checking health, URL returned:{resp.status_code}")
                return self._check_status(resp)
            else:
                self.logger.info(f"Invalid scheme: {self.scheme}")
        except requests.exceptions.ConnectionError:
            self.logger.warning(f"Unable to connect to healthcheck url {self.url}")
        except requests.exceptions.ReadTimeout:
            self.logger.warning(f"Unable to connect to healthcheck url {self.url}")
        except Exception:
            self.logger.exception("Error while performing healthcheck")
            return False

    def _check_status(self, resp):
        return resp.status_code // 100 == 2 or resp.status_code in self.acceptable_errors


class _NoHealthCheck(HealthCheck):
    def __init__(self, logger):
        super().__init__(None, UrlScheme.GET, logger)

    def is_healthy(self):
        return True
