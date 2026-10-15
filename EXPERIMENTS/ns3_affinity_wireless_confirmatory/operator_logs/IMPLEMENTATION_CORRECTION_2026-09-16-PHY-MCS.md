# PHY DATA MCS amendment — 2026-09-16

Full investigation and rationale: see `protocol/PACKET_LEVEL_PROTOCOL_FROZEN.md`,
Amendment 1.1.1 section. Summary:

## What was wrong
`DmgWifiHelper`'s constructor (`dmg-wifi-helper.cc`) hardcodes
`DataMode=DMG_MCS12` for every node's DATA frames via an explicit
`ObjectFactory::Set()` call, unreachable via command-line `Config` override.
The mandatory six-stream smoke gate (RNG 991001) failed: STA 0/3/5 received
zero payload bytes for the full 3s window despite successful association and
SLS beamforming on all 6 stations (control frames use the separate, more
robust DMG_MCS4).

## Investigation (preserved evidence)
- Original failed smoke: `operator_logs/packet-smoke-20260916T121932Z/`
  (process.json, packet_summary.csv, sls_991001.csv, snrValues.csv) — untouched.
- Verbose-text reproduction (`--csv=false --verbose=false`, same RNG/params):
  `operator_logs/packet-smoke-diagnostic-verbose-text/` — confirmed all 6
  STAs associate and complete SLS; all 6 generate ~1293 TX packets; STA 0/3/5
  get 0 RX at both FlowMonitor and application layer for the entire run.
- Controlled MCS sweep (diagnostic image only, source copy outside the SSOT
  tree, never touching the frozen file until the fix was justified):
  `operator_logs/mcs-diagnostic-sweep-v2/` — MCS4-MCS9 all restore ~99.98%
  delivery on all 6 real link positions; MCS12 reproduces the exact original
  failure. This isolated the cause to DATA MCS, not topology/channel-data/
  association/config.
- PHY capacity check against frozen self-test `max_stream_mbps=1194.22`:
  MCS4 (1155 Mbps) insufficient; MCS9 (2502.5 Mbps) has ~110% headroom.
- Cross-checked against independent historical calibration
  (`RESULTS/calibration/external/ns3_simulation_backed_traces.csv`), which
  already labels these same six directed rack pairs at MCS7-MCS9 under
  nominal-los provenance.

## What was changed
`EXPERIMENTS/ns3_affinity_wireless_confirmatory/simulator/evaluate_bplus_affinity_dense.cc`:
1. Added explicit `wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
   "ControlMode", "DMG_MCS4", "DataMode", "DMG_MCS9")` after `DmgWifiHelper`
   construction — one uniform policy for every node/method.
2. Fixed unrelated log-component name mismatch
   (`EvaluateQdDenseScenarioSingleAP` -> `EvaluateBplusAffinityDense`) in the
   unused `--verbose` branch.

No frozen graph identity, placement method, workload, seed, target,
risk/relocation weight, wireless trace, packet-level load anchor, retry
limit, primary endpoint, or statistical test was changed. No scientific
packet cell had executed before this amendment.

## Provenance
- Old SHA-256: `c5fc18832a8357d51168515194d3ca7933f3cfb75db2f75f97b39085158554e6`
- New SHA-256: `63ff5709ea7286d01cbdeaf33549963ba1fb294f383cb11c28b96adf28853454`
- `SHA256SUMS.txt` updated for both the source file and
  `protocol/PACKET_LEVEL_PROTOCOL_FROZEN.md` (Amendment 1.1.1 section added).
- Image will be rebuilt from the amended source; its new content-addressed
  Docker image ID is recorded automatically by `ensure_images()` in the next
  `[6/8]` preflight run and checked against the pinned upstream WiGig commit
  (unchanged: `f3404236d05eb1da1cab80eec06c56ea8ab43f7d` — only the local
  scratch program changed, not the upstream WiGig module).
- Authorized explicitly by user directive "AUTHORIZED: Conditional ns-3 PHY
  configuration amendment" (2026-09-16), following the phased
  investigate/isolate/justify/implement/revalidate procedure specified there.
