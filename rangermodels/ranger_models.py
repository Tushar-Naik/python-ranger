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

import json
from enum import Enum

from common.helper import safe_get

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
    def __init__(self, environment, region, tags):
        self.environment = environment
        self.region = region
        self.tags = tags

    @staticmethod
    def _is_none(val):
        return val is None or len(val) == 0

    def to_dict(self):
        if self.environment is None and self.region is None and self._is_none(self.tags):
            return {}
        return {"environment": self.environment, "region": self.region, "tags": self.tags}


class ServiceNode(object):
    """
    Represents a service that may be discoverable at a host:port over your favourite transport protocol
    """

    def __init__(self,
                 host: str,
                 port: int,
                 node_data: NodeData,
                 healthcheck_status: HealthcheckStatus,
                 last_updated_timestamp: int):
        self.host = host
        self.port = port
        self.node_data = node_data
        self.last_updated_timestamp = last_updated_timestamp
        self.healthcheck_status = healthcheck_status

    @classmethod
    def create(cls, bytes):
        """
        use this factory method to create the ServiceNode from json serialized bytes
        :param bytes: json
        :return: ServiceNode
        """
        node_data_json = json.loads(bytes)
        node_data = None
        if 'nodeData' in node_data_json:
            node_data = NodeData(environment=safe_get(node_data_json['nodeData'], 'environment'),
                                 region=safe_get(node_data_json['nodeData'], 'region'),
                                 tags=safe_get(node_data_json['nodeData'], 'tags'))
        return cls(host=node_data_json['host'],
                   port=int(node_data_json['port']),
                   node_data=node_data,
                   healthcheck_status=HealthcheckStatus(HealthcheckStatus.HEALTHY
                                                        if safe_get(node_data_json, 'healthcheckStatus') == 'healthy'
                                                        else HealthcheckStatus.UNHEALTHY),
                   last_updated_timestamp=int(node_data_json['lastUpdatedTimeStamp']))

    def to_dict(self):
        return {"host": self.host, "port": self.port, "nodeData": self.node_data.to_dict(),
                "healthcheckStatus": self.healthcheck_status.value, "lastUpdatedTimeStamp": self.last_updated_timestamp}

    def get_host(self):
        """
        :return: hostname
        """
        return self.host

    def get_host_port(self):
        """
        :return: host port pair
        """
        return self.host, self.port

    def get_endpoint(self, secure=False):
        """
        :param secure: if the scheme to be used is secure
        :return: endpoint URL
        """
        scheme = "https" if secure else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def get_port(self):
        """
        :return: port
        """
        return self.port

    def get_node_data(self):
        """
        :return: node data
        """
        return self.node_data


class ServiceDetails(object):
    def __init__(self, host, port, environment, namespace, service_name, region=None, tags=None):
        self.host = host
        self.port = port
        self.namespace = namespace
        self.service_name = service_name
        self.environment = environment
        self.region = region
        self.tags = tags

    def get_path(self):
        return f"/{self.namespace}/{self.service_name}/{self.host}:{self.port}"

    def get_root_path(self):
        return f"/{self.namespace}/{self.service_name}"

    def to_dict(self):
        return {"host": self.host, "port": self.port, "environment": self.environment, "namespace": self.namespace,
                "service": self.service_name}


class ClusterDetails(object):
    def __init__(self, zk_string, update_interval_in_secs=1):
        self.zk_string = str(zk_string)
        self.update_interval_in_secs = update_interval_in_secs

    def to_dict(self):
        return {"zk_string": self.zk_string, "update_interval_in_secs": self.update_interval_in_secs}
