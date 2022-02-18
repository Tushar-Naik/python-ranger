import argparse
import logging

from serviceprovider.ranger_models import ClusterDetails, ServiceDetails, UrlScheme
from serviceprovider.service_provider import HealthCheck, RangerServiceProvider

'''
A Python daemon for doing custom Ranger Service Provider registration: 

Writes data in the format (datamodel from ranger):
{"host":"localhost","port":31047,"nodeData":{"environment":"stage"},"healthcheckStatus":"healthy","lastUpdatedTimeStamp":1639044989841}
in path: /namespace/service
at a periodic intervals of --interval (default: 1 second)

How to run this script? 
python3.9 ranger_daemon.py -zk $ZK_CONNECTION_STRING -s $SERVICE_NAME -host $HOST -p $PORT -e $ENV -hcu $HEALTH_CHECK > ranger_daemon.log 

'''

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# create a file handler
handler = logging.FileHandler('ranger_daemon.log')
handler.setLevel(logging.DEBUG)

# create a logging format
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


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
    parser.add_argument('-hcu', '--healthCheckUrl', help='Url where regular health check will be done', default=None)
    parser.add_argument('-hct', '--healthCheckTimeout', help='Url where regular health check will be done', default=0.5)
    args = parser.parse_args()
    return RangerServiceProvider(
        ClusterDetails(args.zkConnectionString, args.interval),
        ServiceDetails(args.host, int(args.port), args.environment, args.namespace, args.service),
        HealthCheck(args.healthCheckUrl, UrlScheme.GET, logger, timeout=args.healthCheckTimeout),
        logger=logger)


ranger_service_provider = initial_program_setup()
ranger_service_provider.start(True)
