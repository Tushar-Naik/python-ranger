# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [2.0.0]

This release brings the client up to parity with the current
[appform-io/ranger](https://github.com/appform-io/ranger) reference
implementation, fixes several bugs present since the 1.x line, and adds a
second, http based transport alongside the existing zookeeper one.

### Fixed

- **Criteria filter silently disabled health/zombie filtering.**
  `RangerServiceFinder.get_all_nodes()` re-filtered the *unfiltered* node list
  when a `criteria_filter` was configured, discarding the health and
  staleness checks entirely. A finder configured with a criteria filter could
  hand out dead or stale nodes.
- **Round robin selection skipped the first node and was not thread safe.**
  `RoundRobinNodeSelector` advanced its cursor before indexing (the first call
  returned index 1, not 0) and mutated the cursor without a lock, which could
  cause duplicate or skipped selections under concurrent use.
- **`ServiceNode.to_dict()` raised when `nodeData` was absent.** A node
  deserialized from a payload with no `nodeData` key left `node_data = None`;
  re-serializing it then raised `AttributeError`.
- **`HealthCheck.is_healthy()` returned `None`, not `False`, on transport
  failures.** Connection errors, timeouts and an invalid scheme all fell
  through without an explicit return, unlike the generic exception handler
  a few lines below, which did return `False`.
- **The finder crashed when handed an already connected zookeeper client.**
  The finder's internal client called `zk.start()` unconditionally; the
  provider already guarded this with a `connected` check, the finder did not.
- **Wrong project URL and malformed license string in packaging metadata.**
- **`get_default_logger()` attached a new log handler on every call.** Every
  instance built without an explicit logger shares the same named logger;
  attaching a handler unconditionally meant every log line was printed once
  per instance ever constructed in the process.

### Added

- **Generic `nodeData`.** `ServiceNode.node_data` now accepts any json
  serializable payload (a plain dict, or an object exposing `to_dict()`)
  instead of the fixed `{environment, region, tags}` shape, matching the
  reference implementation's generic `ServiceNode<T>`. The fixed shape is
  still available as `ShardInfo` (see Changed, below).
- **New `ServiceNode` fields**, matching the current reference implementation:
  `routingWeight` (relative weight for weighted selection, default `1.0`),
  `healthySinceTimeStamp` (when the node most recently became healthy, tracked
  automatically by the provider across ticks), and `portScheme`
  (`http`/`https`/`tcp`, default `http`).
- **A pluggable transport layer** (`transport.base.NodeDataSource` /
  `NodeDataSink`), with the existing zookeeper logic refactored behind it
  (`transport.zk`) with the on-the-wire layout unchanged, and a brand new
  **http hub transport** (`transport.http`) implementing the reference hub's
  REST protocol (`GET /ranger/services/v1`, `GET /ranger/nodes/v1/{ns}/{svc}`,
  `POST /ranger/nodes/v1/add/{ns}/{svc}`). Both the finder and the provider
  accept either transport interchangeably.
- **Shard selection** (`servicefinder.shardselector`): `ShardSelector`
  (`Noop`/`List`/`Matching`) answering a predicate over an in-memory
  `ServiceRegistry` (`servicefinder.serviceregistry`), so a service with many
  instances can be queried for the one serving a particular shard instead of
  any healthy instance. The predicate accepts either a plain
  `callable(node_data) -> bool` or a legacy `Criteria` instance filtering on
  the whole node, so existing `criteria_filter` usage is unaffected.
- **`HierarchicalEnvironmentAwareShardSelector`**: matches nodes by
  `ShardInfo.environment`, preferring the most specific match (e.g.
  `prod.region2.cell5`) and progressively falling back to broader tiers
  (`prod.region2`, then `prod`) when nothing more specific is found.
- **`ServiceFinderHub`** (`servicefinderhub`): polls the registry's
  `services()` on an interval and builds or tears down a per-service finder
  automatically, so a consumer does not need to know the full set of services
  it might call ahead of time and picks up newly registered services without
  a restart. Supports an `excluded_services` set.
- **Multi-check health monitors** (`healthservice`): `IsolatedHealthMonitor`
  runs an independent check on its own thread/interval; a provider can
  register several (`health_monitors=[...]`) and is only published healthy
  while every enabled, non-stale monitor agrees. Ships with
  `PingCheckMonitor` (HTTP ping, damped through a `RollingWindowHealthQueue`
  so one flaky ping does not flip the status), `RotationStatusMonitor`
  (healthy iff a file exists, for controlled drains), and the abstract
  `CountMonitor` (healthy iff a count breaches a threshold), plus
  `DiskSpaceMonitor` as a worked `CountMonitor` example.
- **`ranger_daemon.py --transport {zk,http}`**, with `--hub-host`/
  `--hub-port`/`--hub-secure` for the http case, `--node-data-json` for an
  arbitrary nodeData payload, and `--port-scheme`/`--routing-weight` to
  publish the new `ServiceNode` fields. The Docker entrypoint honours
  `RANGER_TRANSPORT=http` with `HUB_HOST`/`HUB_PORT`/`HUB_SECURE`.

### Changed

- **`NodeData` renamed to `ShardInfo`**, matching the name the reference
  implementation's own example servers use for this exact
  `{environment, region, tags}` shape. `NodeData` and `LegacyNodeData` remain
  as aliases; no import needs to change.
- `ServiceNode`'s constructor gained new keyword arguments
  (`routing_weight`, `healthy_since_timestamp`, `port_scheme`) after the
  existing ones; all existing positional and keyword call sites keep working.
- `ServiceNode.create()`/`from_dict()` accept an optional
  `node_data_deserializer`; without one, `node_data` is left as a plain dict
  rather than being coerced into the old fixed shape. Pass
  `ShardInfo.from_dict` to get the pre-2.0 object back.
- `--environment` on the daemon no longer restricts values to `stage`/`prod`,
  since the hierarchical selector expects dotted values such as
  `prod.region2.cell5`.
- Dropped the unused `python_daemon` dependency; it was declared but never
  imported anywhere in the codebase.

### Migrating from 1.8.4

- If you constructed `NodeData(environment, region, tags)` directly: nothing
  to change, `NodeData` still works identically. Consider switching the
  import to `ShardInfo`, the new canonical name.
- If you relied on `ServiceNode.get_node_data()` always returning a
  `NodeData`-like object: it now returns a plain `dict` by default, unless you
  pass `node_data_deserializer=ShardInfo.from_dict` to
  `RangerServiceFinder`/`ServiceNode.create`.
- If you called `RangerServiceFinder`/`RangerServiceProvider` with only
  positional arguments matching the old signatures: no changes needed, the
  original parameters keep their original positions.
- If you built a `KazooClient` yourself and relied on the finder starting it
  unconditionally: this now mirrors the provider's always-safe
  `if not connected` guard; behaviour is more permissive, not less.

## [1.8.4] and earlier

See the project's git history for the pre-2.0 line.
