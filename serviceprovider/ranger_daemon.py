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

import argparse
import json

from common.helper import get_default_logger
from rangermodels.ranger_models import ClusterDetails, PortSchemes, ServiceDetails, UrlScheme
from serviceprovider.service_provider import HealthCheck, RangerServiceProvider
from transport.http import HttpClientConfig, HttpNodeDataSink
from transport.zk import ZkNodeDataSink

'''
A Python daemon for doing custom Ranger Service Provider registration:

Writes data in the format (datamodel from ranger):
{"host":"localhost","port":31047,"portScheme":"http","nodeData":{"environment":"stage"},
 "healthcheckStatus":"healthy","lastUpdatedTimeStamp":1639044989841,
 "healthySinceTimeStamp":1639044989841,"routingWeight":1.0}

at a periodic interval of --interval (default: 1 second), either directly to
zookeeper (the default) or through an http hub (--transport http).

How to run this script, against zookeeper directly (default)?
python3 ranger_daemon.py -zk $ZK_CONNECTION_STRING -s $SERVICE_NAME -host $HOST -p $PORT -e $ENV -hcu $HEALTH_CHECK > ranger_daemon.log

How to run this script against an http hub instead?
python3 ranger_daemon.py --transport http --hub-host $HUB_HOST --hub-port $HUB_PORT -s $SERVICE_NAME -host $HOST -p $PORT -e $ENV -hcu $HEALTH_CHECK > ranger_daemon.log
'''


def _build_sink(args, logger):
    if args.transport == 'http':
        if not args.hubHost:
            raise ValueError('--hub-host is required when --transport is http')
        config = HttpClientConfig(host=args.hubHost, port=args.hubPort, secure=args.hubSecure)
        return HttpNodeDataSink(config, logger=logger)
    if not args.zkConnectionString:
        raise ValueError('-zk/--zkConnectionString is required when --transport is zk')
    return ZkNodeDataSink(zk_string=args.zkConnectionString, logger=logger)


def initial_program_setup(raw_args=None):
    parser = argparse.ArgumentParser(description="Utility to register a service host/port for ")
    parser.add_argument('--transport', choices=['zk', 'http'], default='zk',
                        help="registry backend to publish to (default: zk)")
    parser.add_argument('-zk', '--zkConnectionString',
                        help='zookeeper connection string, required when --transport is zk')
    parser.add_argument('--hub-host', dest='hubHost', default=None,
                        help='ranger hub hostname, required when --transport is http')
    parser.add_argument('--hub-port', dest='hubPort', type=int, default=80,
                        help='ranger hub port (default: 80)')
    parser.add_argument('--hub-secure', dest='hubSecure', action='store_true',
                        help='use https when talking to the hub')
    parser.add_argument('-n', '--namespace', help='namespace for discovery', default="org")
    parser.add_argument('-s', '--service', help='name of service to be registered', required=True)
    parser.add_argument('-host', '--host', help='hostname of service', required=True)
    parser.add_argument('-p', '--port', help='port of service', required=True, type=int)
    parser.add_argument('--port-scheme', dest='portScheme', choices=list(PortSchemes.ALL), default=PortSchemes.HTTP,
                        help='transport scheme advertised alongside the port (default: http)')
    parser.add_argument('--routing-weight', dest='routingWeight', type=float, default=1.0,
                        help='relative weight published for weighted node selection (default: 1.0)')
    parser.add_argument('-e', '--environment',
                        help='Environment this service is running in. May be a dotted, hierarchical '
                             'value such as prod.region2.cell5 for use with a hierarchical environment '
                             'aware selector',
                        required=True)
    parser.add_argument('-i', '--interval', help='Update interval in seconds', default=1, type=float)
    parser.add_argument('-r', '--region', help='Region if shard info is being provided', default=None)
    parser.add_argument('-t', '--tags', help='Comma separated tag values', default=None)
    parser.add_argument('--node-data-json', dest='nodeDataJson', default=None,
                        help='arbitrary nodeData as a json object, takes precedence over '
                             '--environment/--region/--tags when supplied')
    parser.add_argument('-hcu', '--healthCheckUrl', help='Url where regular health check will be done', default=None)
    parser.add_argument('-hct', '--healthCheckTimeout', help='Url where regular health check will be done',
                        default=0.5, type=float)

    args = parser.parse_args(raw_args)
    logger = get_default_logger()
    logger.info(f'Starting ranger daemon with args: {args}')
    tags = args.tags.split(",") if args.tags is not None else None
    node_data = json.loads(args.nodeDataJson) if args.nodeDataJson is not None else None

    service_details = ServiceDetails(args.host, int(args.port),
                                     environment=args.environment, namespace=args.namespace,
                                     service_name=args.service, region=args.region, tags=tags,
                                     node_data=node_data, port_scheme=args.portScheme,
                                     routing_weight=args.routingWeight)
    return RangerServiceProvider(
        ClusterDetails(args.zkConnectionString, args.interval),
        service_details,
        HealthCheck(args.healthCheckUrl, UrlScheme.GET, logger, timeout=args.healthCheckTimeout),
        logger=logger,
        node_data_sink=_build_sink(args, logger))


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
