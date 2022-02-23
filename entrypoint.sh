#!/bin/bash
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

# run python ranger daemon
ls
echo "Publishing ranger updates on cluster:[$RANGER_ZK] with name:$SERVICE_NAME host:$HOST port:$PORT env:$ENV under namespace:$NAMESPACE and healthCheckUrl:$HEALTH_CHECK"
python3.9 ranger_daemon.py -zk $RANGER_ZK -s $SERVICE_NAME -host $HOST -p $PORT -e $ENV -n $NAMESPACE -hcu $HEALTH_CHECK -r $REGION -t $TAGS > ranger_daemon.log &
pid="$!"

# wait forever
while true
do
  tail -f /dev/null & wait ${!}
done