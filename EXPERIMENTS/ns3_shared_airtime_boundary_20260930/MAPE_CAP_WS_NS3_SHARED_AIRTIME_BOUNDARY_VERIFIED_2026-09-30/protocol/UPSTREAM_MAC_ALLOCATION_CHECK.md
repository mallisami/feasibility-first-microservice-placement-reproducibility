# Pinned WiGig MAC allocation check

This engineering note records the source-level check used before freezing the shared-airtime boundary experiment.

- Upstream repository: `wigig-tools/wigig-module`
- Frozen commit: `f3404236d05eb1da1cab80eec06c56ea8ab43f7d`
- Relevant implementation: `src/wifi/model/dmg-ap-wifi-mac.cc`

At this commit, `DmgApWifiMac::AllocateCbapPeriod(...)` inserts an explicit `CBAP_ALLOCATION` into the AP allocation list. During beacon construction, `m_isCbapOnly` is set according to whether that allocation list is empty. In `DmgApWifiMac::StartDataTransmissionInterval()`, an empty allocation list yields the original full-DTI CBAP behavior; when explicit allocations exist, the AP iterates the allocation list and schedules the listed CBAP/service periods. It does not automatically open the unallocated remainder as a second full-DTI CBAP.

The experiment therefore uses one explicit CBAP equal to 25% of the measured DTI for the scientific shared-resource cells. The remaining DTI is intentionally unallocated.

This source-level check is not trusted alone: `prepare` also performs a packet-level duty-effect gate using a saturated single stream at full DTI versus the 25% allocation. Scientific execution stops unless the limited/full achieved-throughput ratio lies in the frozen interval `[0.05, 0.60]`.

This note verifies software semantics only. It does not constitute physical-radio validation.
