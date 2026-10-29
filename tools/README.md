# Operator and protocol utilities

`instance_supervisor.py` reconciles backend-authored instance demand against source/artifact-pinned Unity builds. Default mode does not spawn processes; `--run` is required. It owns only processes it starts in the current lifetime and does not trust persisted PIDs as permission to stop arbitrary processes.

`seed_local_shops.py` plans a small reachable preservation shop catalog, with actual canonical item identifiers and explicit local prices. `--apply` requires an explicit state directory. It is an operator action, not a hidden first-login mutation.

`avatar_entry_codec.py` encodes/decodes the recovered avatar field representation. `interaction_mapping_bridge.py` contains the offline semantic interaction-ID mapping model. `core_runtime_peer.py` and `social_runtime_peer.py` are synthetic protocol peers, not original-client acceptance tools; explicit network run flags are required. Do not confuse their results with native UI success.

`package_linux_server.py` packages a locally built source-bound server only after verifying its new build report and every artifact. It does not build, deploy or start services. Builds and private state are not shipped here, so packaging requires those missing inputs first.

Private computer-control runners, original binaries, local process receipts, asset extraction tools tied to a personal Steam path and investigation-wide validation scripts are deliberately excluded from this portable operator directory.
