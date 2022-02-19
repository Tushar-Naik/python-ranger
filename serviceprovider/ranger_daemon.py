import argparse

from serviceprovider.helper import get_default_logger
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


def initial_program_setup(raw_args=None):
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

    print(f'{raw_args}')
    args = parser.parse_args(raw_args)
    logger = get_default_logger()
    return RangerServiceProvider(
        ClusterDetails(args.zkConnectionString, args.interval),
        ServiceDetails(args.host, int(args.port), args.environment, args.namespace, args.service),
        HealthCheck(args.healthCheckUrl, UrlScheme.GET, logger, timeout=args.healthCheckTimeout),
        logger=logger)


def ranger_daemon_trigger(raw_args=None):
    """
    Pass in raw_args if you wana trigger via this method
    eg: ['-zk', 'localhost:2181', '-s', 'myapp', '-host', 'localhost', '-p', '9090', '-e', 'stage', '-hcu', 'http://localhost:9091/healthcheck?pretty=true']
    :param raw_args: sys.argv (arguments to the script)
    """
    ranger_service_provider = initial_program_setup(raw_args)
    ranger_service_provider.start(True)


if __name__ == '__main__':
    ranger_daemon_trigger()
