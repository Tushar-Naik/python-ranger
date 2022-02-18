from enum import Enum

"""
includes all models required for the service provider
"""


class HealthcheckStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class UrlScheme(Enum):
    GET = 1
    POST = 2


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
    def __init__(self, host, port, environment, namespace, service_name):
        self.host = host
        self.port = port
        self.environment = environment
        self.namespace = namespace
        self.service_name = service_name

    def get_path(self):
        return f"/{self.namespace}/{self.service_name}/{self.host}:{self.port}"

    def get_root_path(self):
        return f"/{self.namespace}/{self.service_name}"

    def to_dict(self):
        return {"host": self.host, "port": self.port, "environment": self.environment, "namespace": self.namespace,
                "service": self.service_name}


class ClusterDetails(object):
    def __init__(self, zk_string, update_interval):
        self.zk_string = str(zk_string)
        self.update_interval = update_interval

    def to_dict(self):
        return {"zk_string": self.zk_string, "update_interval": self.update_interval}
