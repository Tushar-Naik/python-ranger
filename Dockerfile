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

FROM python:latest
MAINTAINER Tushar Naik "tushar.knaik@gmail.com"

RUN apt-get update -y
RUN apt-get install -y software-properties-common
RUN apt-get install -y python3.9-distutils
RUN apt-get install -y python3.9 python3.9-dev python3.9-distutils
RUN apt-get install -y build-essential libssl-dev libffi-dev python3-pip
RUN apt-get install -y wget
RUN apt-get install -y iputils-ping

# Update pip3
RUN python3.9 -m pip install --upgrade pip setuptools wheel

# Install pip3 requirements
ADD requirements.txt requirements.txt
RUN pip3 install --trusted-host pypi.python.org -r requirements.txt

ADD serviceprovider/ranger_daemon.py ranger_daemon.py
ADD common/job.py job.py
ADD rangermodels/ranger_models.py ranger_models.py
ADD common/exceptions.py exceptions.py
ADD serviceprovider/service_provider.py service_provider.py
ADD serviceprovider/health_check.py health_check.py
ADD common/helper.py helper.py

ADD entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]