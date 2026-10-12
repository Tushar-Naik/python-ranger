# Python Ranger

[![PyPI version](https://img.shields.io/pypi/v/python-ranger-tn?style=for-the-badge)](https://pypi.org/project/python-ranger-tn)
[![Docker Image](https://img.shields.io/docker/v/tusharknaik/python-ranger-daemon?style=for-the-badge)](https://hub.docker.com/repository/docker/tusharknaik/python-ranger-daemon)

A Python client for [Ranger](https://github.com/appform-io/ranger) service
discovery. Lets a Python service register itself (a **service provider**) and
look up other services (a **service finder**), either directly against
Zookeeper or through an http-fronted Ranger hub, with the same wire format and
data model used by the Java reference implementation.

See `CHANGELOG.md` for what's new since the 1.x line, including a migration
section if you're upgrading.

## Contents

1. [Installation](#installation)
2. [Transports](#transports)
3. [Service Finder](#service-finder)
4. [Service Provider](#service-provider)
5. [Shard selection](#shard-selection)
6. [Dynamic multi-service discovery (hub)](#dynamic-multi-service-discovery-hub)
7. [Health monitors](#health-monitors)
8. [Ranger Daemon](#ranger-daemon)
9. [Under the hood](#under-the-hood)

## Installation

```shell
python3 -m pip install python-ranger-tn
```

## Transports

Every example below works against either backend; only the object you build
to talk to the registry changes.

**Zookeeper**, talking to the cluster directly:

```python
from transport.zk import ZkNodeDataSource, ZkNodeDataSink

source = ZkNodeDataSource(zk_string='localhost:2181', namespace='org')  # for a finder
sink = ZkNodeDataSink(zk_string='localhost:2181')                      # for a provider
```

**Http hub**, when Zookeeper is not exposed directly and a Ranger hub server
fronts it instead:

```python
from transport.http import HttpClientConfig, HttpNodeDataSource, HttpNodeDataSink

config = HttpClientConfig(host='ranger-hub.internal', port=80, secure=False)
source = HttpNodeDataSource(config)  # for a finder
sink = HttpNodeDataSink(config)      # for a provider
```

You will not normally build these yourself: `RangerServiceFinder` and
`RangerServiceProvider` build a Zookeeper one for you by default, you only
need to construct a transport explicitly to use the http hub instead, or to
share a connection across multiple finders/providers.

## Service Finder

A service finder discovers the live host:port pairs of a service, so your
code can make calls to one of them directly.

### Installation-free quick start (Zookeeper, default transport)

```python
import requests
from rangermodels import *
from servicefinder import RangerServiceFinder, RoundRobinNodeSelector

ranger = RangerServiceFinder(cluster_details=ClusterDetails(zk_string='localhost:2181', update_interval_in_secs=1),
                             namespace="org",
                             services=["serviceA", "serviceB"],
                             selector=RoundRobinNodeSelector())  # optional

ranger.start()  # starts a background thread refreshing the node list

node = ranger.get_node("serviceA")
response = requests.get(node.get_endpoint() + "/my/api")

# the full, healthy list, if you want to pick among them yourself
nodes = ranger.get_all_nodes("serviceB")

ranger.stop()
```

One background thread refreshes every registered service's node list at
`update_interval_in_secs`. Health and staleness ("zombie") filtering is always
applied before a `criteria_filter` narrows the result further, so a custom
filter never accidentally reintroduces an unhealthy or stale node.

The one difference from the java library's finder API: there, you build one
finder per service; here, one finder manages every service you give it. If
you want java-style one-finder-per-service instead (for example, to use
different selectors per service), use `SimpleUnshardedServiceFinder` directly
-- see [Shard selection](#shard-selection) below.

### Against an http hub instead

```python
from transport.http import HttpClientConfig
from servicefinder import RangerServiceFinder

ranger = RangerServiceFinder(cluster_details=ClusterDetails('unused-when-node_data_source-is-given'),
                             namespace="org", services=["serviceA"],
                             node_data_source=HttpNodeDataSource(HttpClientConfig(host='ranger-hub.internal')))
ranger.start()
```

## Service Provider

A service provider publishes your service's host:port, periodically, so
finders can discover it.

```python
from rangermodels import *
from serviceprovider import RangerServiceProvider, HealthCheck

ranger = RangerServiceProvider(cluster_details=ClusterDetails(zk_string='localhost:2181', update_interval_in_secs=1),
                               service_details=ServiceDetails(host='localhost', port=12211, environment='stage',
                                                              namespace='myorg',
                                                              service_name='python-test'),
                               health_check=HealthCheck(url='localhost:12211/health', scheme=UrlScheme.GET))

ranger.start()               # background thread
ranger.start(block=True)     # or block the current thread until interrupted

ranger.stop()
```

### Publishing custom node data

`nodeData` is not restricted to `{environment, region, tags}` -- it accepts
any json serializable value:

```python
ServiceDetails(host='localhost', port=12211, namespace='myorg', service_name='python-test',
              node_data={'shardId': 7, 'version': '1.4.2'})
```

### Against an http hub instead

```python
from transport.http import HttpClientConfig, HttpNodeDataSink

ranger = RangerServiceProvider(cluster_details=ClusterDetails('unused-when-node_data_sink-is-given'),
                               service_details=ServiceDetails('localhost', 12211, namespace='myorg', service_name='python-test'),
                               node_data_sink=HttpNodeDataSink(HttpClientConfig(host='ranger-hub.internal')))
```

## Shard selection

When a service has many instances, each serving a different partition of
data (a shard), a plain "give me any healthy node" is not enough -- you need
the instance that owns the shard you care about. `nodeData` is what you shard
on:

```python
from rangermodels import ServiceNode, Service
from servicefinder import SimpleShardedServiceFinder
from transport.zk import ZkNodeDataSource

finder = SimpleShardedServiceFinder(Service('org', 'serviceA'), ZkNodeDataSource(zk_string='localhost:2181'))
finder.refresh()  # or call this on a timer yourself

nodes = finder.get_all_nodes(criteria=lambda node_data: node_data['shardId'] == 3)
node = finder.get_node(criteria=lambda node_data: node_data['shardId'] == 3)
```

Use `SimpleUnshardedServiceFinder` instead when every healthy node is
interchangeable (this is what `RangerServiceFinder` uses internally).

`criteria` also accepts a legacy `Criteria` instance (filtering on the whole
`ServiceNode`, not just its `node_data`) for anyone already using
`criteria_filter` with `RangerServiceFinder`.

### Hierarchical, environment-aware fallback

If your `nodeData` is a `ShardInfo` (the conventional
`{environment, region, tags}` shape) and services are deployed per cell
(`prod.region2.cell5`), `HierarchicalEnvironmentAwareShardSelector` tries the
most specific environment first and falls back to broader ones:

```python
from servicefinder.shardselector import HierarchicalEnvironmentAwareShardSelector
from servicefinder.simple_finder import SimpleServiceFinder
from servicefinder.serviceregistry import MapBasedServiceRegistry

finder = SimpleServiceFinder(service, source, MapBasedServiceRegistry(service),
                             HierarchicalEnvironmentAwareShardSelector('prod.region2.cell5'))
```

A caller in `prod.region2.cell5` finds a same-cell instance if one exists,
otherwise one tagged just `prod.region2`, otherwise anything tagged `prod`.

## Dynamic multi-service discovery (hub)

`RangerServiceFinder` requires every service name upfront. `ServiceFinderHub`
instead polls the registry for the services that currently exist and builds
or tears down finders for you automatically:

```python
from servicefinderhub import ServiceFinderHub, unsharded_finder_factory
from transport.zk import ZkNodeDataSource

source = ZkNodeDataSource(zk_string='localhost:2181', namespace='org')
hub = ServiceFinderHub(source, unsharded_finder_factory(source), excluded_services={'noisy-internal-service'})
hub.start()

finder = hub.finder(Service('org', 'serviceA'))  # None if not (yet) discovered
if finder is not None:
    node = finder.get_node()

hub.stop()
```

Use `sharded_finder_factory` instead for sharded services.

## Health monitors

A provider can aggregate several independent health checks instead of a
single url ping; the published status is healthy only while every enabled,
non-stale monitor agrees:

```python
from healthservice import TimeEntity
from healthservice.monitors import PingCheckMonitor, RotationStatusMonitor

monitors = [
    PingCheckMonitor(TimeEntity.every_second(), url='http://localhost:12211/ping'),
    RotationStatusMonitor('/var/run/service-in-rotation'),
]

ranger = RangerServiceProvider(cluster_details, service_details, health_monitors=monitors)
```

`PingCheckMonitor` damps a single flaky ping through a rolling window so it
does not flip the published status; `RotationStatusMonitor` is healthy
exactly while a file exists (remove it to drain traffic during a controlled
shutdown). `CountMonitor` (and the `DiskSpaceMonitor` example built on it) is
healthy while some countable value stays within a threshold. Subclass
`IsolatedHealthMonitor` directly for anything else.

## Ranger Daemon

A light daemon that runs alongside software that cannot embed this library
directly (a non-Python service, or one that cannot take the dependency), and
publishes updates on its behalf for as long as it stays healthy.

### 1. Simple usage

```shell
# against zookeeper directly (default)
python3 serviceprovider/ranger_daemon.py -zk localhost:2181 -s myapp -host localhost -p 12211 -n org -e stage -hcu 'http://localhost:12211/healthcheck?pretty=true'

# against an http hub instead
python3 serviceprovider/ranger_daemon.py --transport http --hub-host ranger-hub.internal --hub-port 80 -s myapp -host localhost -p 12211 -n org -e stage -hcu 'http://localhost:12211/healthcheck?pretty=true'

# publishing arbitrary nodeData instead of environment/region/tags
python3 serviceprovider/ranger_daemon.py -zk localhost:2181 -s myapp -host localhost -p 12211 -n org -e stage --node-data-json '{"shardId": 3}'
```

### 2. Import based usage

```shell
python3 -m pip install python-ranger-tn
```

```python
import sys
from serviceprovider.ranger_daemon import ranger_daemon_trigger

ranger_daemon_trigger(sys.argv[1:])
```

### 3. Docker based

Run this daemon as a sidecar container alongside an existing, non-integrated
service. Images are on
[DockerHub](https://hub.docker.com/repository/docker/tusharknaik/python-ranger-daemon).

| Env Variable      | Description                                                    |
|--------------------|-----------------------------------------------------------------|
| RANGER_TRANSPORT  | `zk` (default) or `http`                                        |
| RANGER_ZK         | Zookeeper connection string, required when RANGER_TRANSPORT=zk  |
| HUB_HOST          | Ranger hub hostname, required when RANGER_TRANSPORT=http         |
| HUB_PORT          | Ranger hub port (default: 80)                                   |
| HUB_SECURE        | set (to any value) to use https talking to the hub              |
| HOST              | Hostname                                                         |
| PORT              | Port                                                             |
| SERVICE_NAME      | Name of service                                                  |
| ENV               | Environment, may be dotted/hierarchical e.g. prod.region2.cell5 |
| NAMESPACE         | Namespace in the registry                                       |
| HEALTH_CHECK      | [optional] GET healthcheck URL to be used for pings              |
| REGION            | [optional] Region value                                          |
| TAGS              | [optional] Comma separated tags                                  |

```shell
docker run --rm -d -e RANGER_ZK=<zookeeper_info> -e SERVICE_NAME=<name_of_service> -e HOST=<host_of_machine> -e PORT=<port> -e ENV=<environment> -e NAMESPACE=<namespace> -e HEALTH_CHECK=<health_check_url> --name python-ranger-daemon tusharknaik/python-ranger-daemon:2.0.0
```

Running against an http hub instead:

```shell
docker run --rm -d -e RANGER_TRANSPORT=http -e HUB_HOST=<hub_host> -e HUB_PORT=80 -e SERVICE_NAME=<name_of_service> -e HOST=<host_of_machine> -e PORT=<port> -e ENV=<environment> -e NAMESPACE=<namespace> -e HEALTH_CHECK=<health_check_url> --name python-ranger-daemon tusharknaik/python-ranger-daemon:2.0.0
```

## Under the hood

The daemon/thread writes nodes in the following format:

```json
{
  "host": "localhost",
  "port": 12211,
  "portScheme": "http",
  "nodeData": {
    "environment": "stage",
    "tags": ["identity", "auth"],
    "region": "IN-nm"
  },
  "healthcheckStatus": "healthy",
  "lastUpdatedTimeStamp": 1639044989841,
  "healthySinceTimeStamp": 1639044989841,
  "routingWeight": 1.0
}
```

`nodeData` may be any json serializable value, not only the shape shown above.

Against zookeeper, this is published at `/$NAMESPACE/$SERVICE_NAME/$HOST:$PORT`
as an ephemeral node, at a periodic interval of `--interval`
(default: 1 second). Against an http hub, the same payload is `POST`ed to
`/ranger/nodes/v1/add/$NAMESPACE/$SERVICE_NAME` on the same interval.

**The following is taken care of either way:**

- Infinite retry and connection reattempts in case of connection issues
- Proper cleanup of connections to get rid of ephemeral nodes (zookeeper)
- Proper logging
- Continuous health check pings on a particular health check url if required [optional]
- Combining several independent health monitors into one published status [optional]
