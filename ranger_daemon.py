import argparse
from datetime import timedelta
import json
import logging
from enum import Enum
from kazoo.client import KazooClient
import time
from kazoo.retry import KazooRetry

from timeloop import Timeloop

'''
A Python daemon for doing custom Ranger Service Provider registration: 

Writes data in the format (datamodel from ranger):
{"host":"localhost","port":31047,"nodeData":{"environment":"stage"},"healthcheckStatus":"healthy","lastUpdatedTimeStamp":1639044989841}
in path: /namespace/service
at a periodic intervals of --interval (default: 1 second)

Takes care of the following :
- Infinite retry and connection reattempts in case of zk connection issues 
- proper cleanup of zk connections to get rid of ephemeral nodes
- Proper logging  

How to run this script? 
python3.9 ranger_discovery.py -zk $ZK_CONNECTION_STRING -s $SERVICE_NAME -host $HOST -p $PORT -e $ENV > ranger_discovery.log 

'''


def current_milli_time():
    return round(time.time() * 1000)


tl = Timeloop()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# create a file handler
handler = logging.FileHandler('ranger_daemon.log')
handler.setLevel(logging.DEBUG)

# create a logging format
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class HealthcheckStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class NodeData(object):
    def __init__(self, environment):
        self.environment = environment

    def to_dict(self):
        return {"environment": self.environment}


class ServiceNode(object):
    def __init__(self,
                 host,
                 port,
                 node_data: NodeData,
                 healthcheck_status: HealthcheckStatus,
                 last_updated_timestamp):
        self.host = host
        self.port = port
        self.node_data = node_data
        self.last_updated_timestamp = last_updated_timestamp
        self.healthcheck_status = healthcheck_status

    def to_dict(self):
        return {"host": self.host, "port": self.port, "nodeData": self.node_data.to_dict(),
                "healthcheckStatus": self.healthcheck_status.value, "lastUpdatedTimeStamp": self.last_updated_timestamp}


class ServiceDetails(object):
    def __init__(self, host, port, environment, namespace, service):
        self.host = host
        self.port = port
        self.environment = environment
        self.namespace = namespace
        self.service = service

    def get_path(self):
        return f"/{self.namespace}/{self.service}/{self.host}:{self.port}"

    def get_root_path(self):
        return f"/{self.namespace}/{self.service}"

    def to_dict(self):
        return {"host": self.host, "port": self.port, "environment": self.environment, "namespace": self.namespace,
                "service": self.service}


class ClusterDetails(object):
    def __init__(self, zk_string, update_interval):
        self.zk_string = str(zk_string)
        self.update_interval = update_interval

    def to_dict(self):
        return {"zk_string": self.zk_string, "update_interval": self.update_interval}


def default_serialize_func(o):
    """
    Use like this: logging.debug(f"print this object: {json.dumps(myobject, indent=4, sort_keys=True, default=default_serialize_func)}")
    """
    if hasattr(o, '__dict__'):
        return o.__dict__
    return f"<could not serialize {o.__class__}>"


class RangerClient(object):
    def __init__(self, zk: KazooClient, cluster_details: ClusterDetails, service_details: ServiceDetails):
        self.zk = zk
        self.cluster_details = cluster_details
        self.service_details = service_details

    def start(self):
        self.zk.start()

    def stop(self):
        self.zk.stop()

    def update_tick(self):
        node_data = NodeData(self.service_details.environment)
        service_node = ServiceNode(self.service_details.host, self.service_details.port, node_data,
                                   HealthcheckStatus.HEALTHY, current_milli_time())
        data_bytes = str.encode(json.dumps(service_node.to_dict()))
        logger.info(f"Updating with: {str(data_bytes)}")
        if self.zk.exists(self.service_details.get_path()):
            self.zk.set(self.service_details.get_path(), data_bytes)
        else:
            # ensure that you create only ephemeral nodes
            self.zk.ensure_path(self.service_details.get_root_path())
            self.zk.create(self.service_details.get_path(), data_bytes, ephemeral=True)


def stop_zk_updates():
    logger.info(".. Stopping updates to zk")
    ranger_client.stop()


def initial_program_setup():
    parser = argparse.ArgumentParser(description="Utility to register a service host/port for ")
    parser.add_argument('-zk', '--zkConnectionString', help='zookeeper connection string', required=True)
    parser.add_argument('-n', '--namespace', help='namespace for discovery', default="org")
    parser.add_argument('-s', '--service', help='name of service to be registered', required=True)
    parser.add_argument('-host', '--host', help='hostname of service', required=True)
    parser.add_argument('-p', '--port', help='port of service', required=True, type=int)
    parser.add_argument('-e', '--environment', choices=['stage', 'prod'],
                        help='Environment on which service is running',
                        required=True)
    parser.add_argument('-i', '--interval', help='Update interval in seconds', default=1)
    args = parser.parse_args()

    zk = args.zkConnectionString
    logger.info(zk)
    return ClusterDetails(zk, args.interval), ServiceDetails(args.host, int(args.port), args.environment,
                                                             args.namespace, args.service)


cluster_details, service_details = initial_program_setup()

logger.info(json.dumps(cluster_details, default=default_serialize_func))
logger.info(json.dumps(service_details, default=default_serialize_func))
ranger_client = RangerClient(
    KazooClient(hosts=cluster_details.zk_string,
                # proper infinite retries to ensure we handle network flakiness
                connection_retry=KazooRetry(max_tries=float('inf'), delay=1, max_delay=5)),
    cluster_details,
    service_details)

ranger_client.start()


@tl.job(interval=timedelta(seconds=cluster_details.update_interval))
def ranger_update_tick():
    try:
        ranger_client.update_tick()
    except Exception:
        logger.exception("Error while updating zk")


tl.start(block=True)
logger.info("Stopping all things..")
stop_zk_updates()
