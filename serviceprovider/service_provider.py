import sys
from datetime import timedelta
import json
import logging
import signal
import requests
import time
from kazoo.retry import KazooRetry
from kazoo.client import KazooClient

from serviceprovider.exceptions import StopRangerUpdate
from serviceprovider.job import Job
from serviceprovider.ranger_models import ClusterDetails, ServiceDetails, HealthcheckStatus, NodeData, ServiceNode, \
    UrlScheme

'''
This is a ServiceProvider implementation for doing regular ranger updates on zookeeper
You may run this in background or run it in foreground by blocking your current thread.

Takes care of the following :
- Infinite retry and connection reattempts in case of zk connection issues 
- Proper cleanup of zk connections to get rid of ephemeral nodes
- Proper logging  
= Does continuous health check pings on a particular health check url if required [optional]

'''


def _current_milli_time():
    return round(time.time() * 1000)


def _service_shutdown(signum, frame):
    raise StopRangerUpdate


def _default_serialize_func(o):
    """
    Use like this: logging.debug(f"print this object: {json.dumps(myobject, indent=4, sort_keys=True, default=default_serialize_func)}")
    """
    if hasattr(o, '__dict__'):
        return o.__dict__
    return f"<could not serialize {o.__class__}>"


def _get_default_logger():
    logger = logging.getLogger('ranger')
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)
    return logger


class _RangerClient(object):
    def __init__(self, zk: KazooClient, cluster_details: ClusterDetails, service_details: ServiceDetails, logger):
        self.zk = zk
        self.cluster_details = cluster_details
        self.service_details = service_details
        self.logger = logger

    def start(self):
        self.zk.start()

    def stop(self):
        self.zk.stop()

    def update_tick(self, status=HealthcheckStatus.HEALTHY):
        node_data = NodeData(self.service_details.environment)
        service_node = ServiceNode(self.service_details.host, self.service_details.port, node_data,
                                   status, _current_milli_time())
        data_bytes = str.encode(json.dumps(service_node.to_dict()))
        self.logger.info(f"Updating with: {str(data_bytes)}")
        if self.zk.exists(self.service_details.get_path()):
            self.zk.set(self.service_details.get_path(), data_bytes)
        else:
            # ensure that you create only ephemeral nodes
            self.zk.ensure_path(self.service_details.get_root_path())
            self.zk.create(self.service_details.get_path(), data_bytes, ephemeral=True)


class HealthCheck(object):
    def __init__(self, url, scheme: UrlScheme, logger, data=None, headers=None, timeout=1.0, acceptable_errors=None):
        self.url = url
        self.scheme = scheme
        self.logger = logger
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


class RangerServiceProvider(object):
    """
    Initialize this class to be able to start and create a Ranger Updater
    """

    def __init__(self, cluster_details: ClusterDetails, service_details: ServiceDetails,
                 health_check: HealthCheck, logger=None):
        """
        :param cluster_details: Zookeeper cluster details
        :param service_details: Service details like name, host, port etc
        :param health_check: health check url details if any
        :param logger: optional logger
        """
        self.cluster_details = cluster_details
        self.service_details = service_details
        self.is_running = False
        self.logger = logger if logger is not None else _get_default_logger()
        self.health_check = health_check if health_check is not None else _NoHealthCheck(logger)
        self.ranger_client = _RangerClient(
            KazooClient(hosts=self.cluster_details.zk_string,
                        # proper infinite retries to ensure we handle network flakiness
                        connection_retry=KazooRetry(max_tries=float('inf'), delay=1, max_delay=5)),
            self.cluster_details,
            self.service_details,
            self.logger)
        self.job = Job(timedelta(seconds=self.cluster_details.update_interval), self._ranger_update_tick)

    def _stop_zk_updates(self):
        if not self.is_running:
            self.logger.info("Already stopped")
            return
        self.logger.info("Stopping all updates to zk and cleaning up..")
        self.ranger_client.stop()
        self.is_running = False

    def _block_main_thread(self):
        signal.signal(signal.SIGTERM, _service_shutdown)
        signal.signal(signal.SIGINT, _service_shutdown)
        while True:
            try:
                time.sleep(1)
            except StopRangerUpdate:
                self._stop_zk_updates()
                break

    def _ranger_update_tick(self):
        """
        Used to perform a single tick update to zookeeper. Handles error scenarios. Does healthcheck if necessary
        """
        try:
            if self.health_check.is_healthy():
                self.ranger_client.update_tick(HealthcheckStatus.HEALTHY)
            else:
                self.ranger_client.update_tick(HealthcheckStatus.UNHEALTHY)
        except Exception:
            self.logger.exception("Error while updating zk")

    def start(self, block=False):
        """
        Creates a Thread that updates zookeeper with service health state updates at regular intervals
        :param block: send block as true if you wish to block the current thread (and wait for an interrupt to stop)
        """
        if self.is_running:
            self.logger.info("Already started")
            return
        self.is_running = True
        self.logger.info(json.dumps(self.cluster_details, default=_default_serialize_func))
        self.ranger_client.start()
        self.job.daemon = not block
        self.job.start()
        if block:
            self._block_main_thread()
            self.job.stop()

    def stop(self):
        """
        Stop zookeeper updates
        """
        self._stop_zk_updates()
