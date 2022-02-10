FROM python:latest
MAINTAINER Tushar Naik "tushar.naik@phonepe.com"

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

ADD ranger_daemon.py ranger_daemon.py
ADD entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]