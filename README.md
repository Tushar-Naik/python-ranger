# Python ranger daemon

This is a simple light daemon that can run alongside your software to provide regular service discovery updates to zookeeper.
Check [Ranger]([https://github.com/appform-io/ranger]) for more details. You'll need it to follow some jargon being used in this readme.

## Intent
Ideally, you would directly use the standard Ranger java client to deeply integrate the service's health updates with ranger.<br>  
In scenarios where you can't do the above, you can rely on this daemon. 
Say you need discovery updates to be published for a service written in a langauge other than java, or you are unable to add the ranger dependency directly, in your java application.

The intent of this daemon is to run along-side your application and publish updates, as long as your service is up and healthy.
Currently, support has been added for a dockerized setup.
You can use docker compose to run your service and this daemon as a multi container docker application<br>
After this, your application should be ready for service discovery.

### How to run
The following is the docker command to run the script, using environment variables
```shell
docker run --rm -d -e RANGER_ZK=<zookeeper_info> -e SERVICE_NAME=<name_of_service> -e HOST=<host_of_machine> -e PORT=<port> -e ENV=<environment> -e NAMESPACE=<namespace> --name python-ranger-daemon tusharknaik/python-ranger-daemon:1.0
```

Here is an example for running it on a Mac machine, assuming your zookeeper is already running on `localhost:2181` (notice the network being set to `host` and zookeeper being sent as `host.docker.internal` for connecting to localhost from within docker)
```shell
docker run --rm -d --network host -e RANGER_ZK=host.docker.internal:2181 -e SERVICE_NAME=python-test -e HOST=localhost -e PORT=12211 -e ENV=stage -e NAMESPACE=myorg --name python-ranger-daemon tusharknaik/python-ranger-daemon:1.0
```

### Docker
Docker containers are available on the [DockerHub](https://hub.docker.com/repository/docker/tusharknaik/python-ranger-daemon).

---

## Under the hood
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
in the path: /$NAMESPACE/$SERVICE_NAME
at a periodic intervals of --interval (default: 1 second)

**Takes care of the following :**
- Infinite retry and connection reattempts in case of zk connection issues
- Proper cleanup of zk connections to get rid of ephemeral nodes
- Proper logging

### In the works
- [ ] Healthcheck capabilities before updating zookeeper
