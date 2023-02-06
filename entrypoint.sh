#!/bin/bash

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

set -x

pid=0

# SIGUSR1-handler
my_handler() {
  echo "my_handler"
}

# SIGTERM-handler
term_handler() {
  if [ $pid -ne 0 ]; then
    kill -SIGTERM "$pid"
    wait "$pid"
  fi
  exit 143; # 128 + 15 -- SIGTERM
}

# setup handlers
# on callback, kill the last background process, which is `tail -f /dev/null` and execute the specified handler
trap 'kill ${!}; my_handler' SIGUSR1
trap 'kill ${!}; term_handler' SIGTERM

ls

# run python ranger daemon
echo "Publishing ranger updates on cluster:[$RANGER_ZK] with name=$SERVICE_NAME host=$HOST port=$PORT env=$ENV under namespace=$NAMESPACE and healthCheckUrl=$HEALTH_CHECK"
PYTHONPATH=../:. python3.9 serviceprovider/ranger_daemon.py -zk $RANGER_ZK -s $SERVICE_NAME -host $HOST -p $PORT -e $ENV -n $NAMESPACE -hcu $HEALTH_CHECK ${REGION:+ -r $REGION} ${TAGS:+ -t $TAGS} > ranger_daemon.log &
pid="$!"

# wait forever
while true
do
  tail -f /dev/null & wait ${!}
done