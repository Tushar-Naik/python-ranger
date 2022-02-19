# Python Ranger
[![PyPI version](https://img.shields.io/pypi/v/serviceprovider?style=for-the-badge)](https://pypi.org/project/serviceprovider)
[![Docker Image](https://img.shields.io/docker/v/tusharknaik/python-ranger-daemon?style=for-the-badge)](https://hub.docker.com/repository/docker/tusharknaik/python-ranger-daemon)

Before you start, you might wanna check [Ranger](https://github.com/appform-io/ranger) for more details. You'll need it
to follow some jargon being used in this readme.

There are 2 sections in here.

1. [Ranger Service Provider](#ranger-service-provider)
2. [Ranger Daemon](#ranger-daemon-setup)

## Ranger Service Provider

A service provider in Ranger is something can be used to broadcast that a service is available at some host:port, where
certain clients can connect and request services (make http calls). This broadcast is essentially done using zookeeper.
The following python class helps you do the same for a python script It follows the same models as present in the main
java library.

Similar details can be found at [PyPi](https://pypi.org/project/serviceprovider/)

### Installation

```shell
python3.9 -m pip install serviceprovider
```

### Usage

```python
from serviceprovider.ranger_models import *
from serviceprovider import RangerServiceProvider, HealthCheck

# Create the ranger service provider
ranger = RangerServiceProvider(cluster_details=ClusterDetails(zk_string='localhost:2181', update_interval=1),
                               service_details=ServiceDetails(host='localhost', port=12211, environment='stage',
                                                              namespace='myorg',
                                                              service_name='python-test'),
                               health_check=HealthCheck(url='localhost:12211/health', scheme=UrlScheme.GET))

## Start the updates in background (this will update zookeeper at regular intervals)
ranger.start()

## You may also start the updates and block your current thread (until we hit an interrupt)
ranger.start(block=True)

## When you wish to stop updates
ranger.stop()
```

## Ranger Daemon setup

This section deals with using the code as a simple light daemon that can run alongside your software to provide regular
service discovery updates to zookeeper. As usual, check [Ranger](https://github.com/appform-io/ranger) for more details.

## Intent

Ideally, you would directly use the standard Ranger java client to deeply integrate the service's health updates with
ranger.<br>  
In scenarios where you can't do the above, you can rely on this daemon. Say you need discovery updates to be published
for a service written in a langauge other than java, or you are unable to add the ranger dependency directly, in your
java application.

The intent of this daemon is to run along-side your application and publish updates, as long as your service is up and
healthy. Currently, support has been added for a dockerized setup. You can use docker compose to run your service and
this daemon as a multi container docker application<br>
After this, your application should be ready for service discovery.

### How to run

The following is the docker command to run the script, using environment variables

| Env Variable | Description                                         |
|--------------|-----------------------------------------------------|
| HOST         | Hostname                                            |
| PORT         | Port                                                |
| RANGER_ZK    | Zookeeper connection string                         |
| SERVICE_NAME | Name of service                                     |
| ENV          | Environment (stage/prod)                            |
| NAMESPACE    | Namespace in zookeeper                              |
| HEALTH_CHECK | [optional] GET healthcheck URL to be used for pings |

```shell
docker run --rm -d -e RANGER_ZK=<zookeeper_info> -e SERVICE_NAME=<name_of_service> -e HOST=<host_of_machine> -e PORT=<port> -e ENV=<environment> -e NAMESPACE=<namespace> -e HEALTH_CHECK=<health_check_url> --name python-ranger-daemon tusharknaik/python-ranger-daemon:1.6
```

Here is an example for running it on a Mac machine, assuming your zookeeper is already running on `localhost:2181` (
notice the network being set to `host` and zookeeper being sent as `host.docker.internal` for connecting to localhost
from within docker)

```shell
docker run --rm -d --network host -e RANGER_ZK=host.docker.internal:2181 -e SERVICE_NAME=python-test -e HOST=localhost -e PORT=12211 -e ENV=stage -e NAMESPACE=myorg -e HEALTH_CHECK="localhost:12211/health" --name python-ranger-daemon tusharknaik/python-ranger-daemon:1.6
```

### Docker

Docker containers are available on
the [DockerHub](https://hub.docker.com/repository/docker/tusharknaik/python-ranger-daemon).

---

### Under the hood

The daemon will write data to zookeeper in the following format (datamodel from ranger):

```json
{
  "host": "localhost",
  "port": 12211,
  "nodeData": {
    "environment": "stage"
  },
  "healthcheckStatus": "healthy",
  "lastUpdatedTimeStamp": 1639044989841
}
```

Updates will be puslised in the path: /$NAMESPACE/$SERVICE_NAME at a periodic intervals of --interval (default: 1 second)

**Takes care of the following :**

- Infinite retry and connection reattempts in case of zk connection issues
- Proper cleanup of zk connections to get rid of ephemeral nodes
- Proper logging
- Does continuous health check pings on a particular health check url if required [optional]
