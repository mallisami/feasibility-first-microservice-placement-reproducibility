# Redactions and Edits Relative to the Files as Executed

The package is a copy of the authors' verified evidence. Three kinds of change were made in the copy, all documented here so that a reviewer can tell an edit from an observation.

## 1. One public IP address removed (three files)

The fault-path study reports recorded the public IP address of the authors' cloud virtual machine in a header line. The address is not needed to interpret or reproduce anything and the machine is still in use, so the literal address was replaced by `<public-ip-redacted-for-distribution>` in exactly one line of each file. Nothing else in these files changed.

| File | SHA-256 as executed (from `RESULTS/se8_corrected_campaign/SHA256SUMS.txt`) |
|---|---|
| `RESULTS/se8_corrected_campaign/AZURE_PREFLIGHT_REPORT.md` | `6c2fdedb422da6e88c271e290a814a4da37ef765dffb908025b8915bbcbd3655` |
| `RESULTS/se8_corrected_campaign/SAFETY_AUDIT_REPORT.md` | `084e4bcf285010c6ccfc6c7416d1e7a08ecffdeddaa87d0d77ca4b4cfbd71a26` |
| `RESULTS/se8_corrected_campaign/PROTOCOL_FROZEN.md` | `6a834c7e8e950013e9930a6cbd49549feba0063671a38b9896fba0476c64eff5` |

Consequence: the study's own internal manifests (`RESULTS/se8_corrected_campaign/SHA256SUMS.txt` and `RELEASE_SHA256SUMS.txt`) report a mismatch for these three files only. The root `SHA256SUMS.txt` records the files as shipped. All 30 trial records (`trial_results.csv`, `evidence/`) are untouched.

## 2. Six path edits in the extension-study scripts

Listed line by line in `EXTENSION_STUDIES/PATCH_NOTES.md`. They make the scripts run from the package root. `EXTENSION_STUDIES/SHA256SUMS_as_executed.txt` holds the pre-edit hashes.

## 3. Documents written for this package

`README.md`, `REVIEWER_WORKFLOW.md`, `CLAIMS_TO_EVIDENCE.md`, `REPRODUCIBILITY.md`, `ENVIRONMENT.md`, `PACKAGE_INVENTORY.md`, `AUTHOR_ACTIONS_BEFORE_DEPOSIT.md`, `EVIDENCE_SCOPE.md`, `EXPERIMENT_COMPLETENESS_MATRIX.md`, this file, `EXTENSION_STUDIES/README.md`, `EXPERIMENTS/ns3_affinity_wireless_confirmatory/raw_trace_archive/README.md`, `runbooks/QUICKSTART.md`, `tools/verify_package.py`, `tools/regenerate_manifest.py`, `tools/regenerate_manifest.sh`, `tools/regenerate_manifest.ps1`.

## What was not changed

No raw observation, derived result, protocol content, configuration, or seed was altered. Internal working notes, editorial audit reports, manuscript sources, and chat handoff files from the authors' workspace are excluded from this reproducibility package.

## Not redacted, by design

The hostname `mcb-k8s-v137` and the cloud default user path `/home/azureuser/...` remain in operator logs, run logs and pre-execution manifests (about 550 files). They identify the recorded runtime paths of the campaigns and are not credentials; removing them would alter frozen records whose hashes were recorded at execution time.

## 4. Multi-host machine identity handling

The 1 October three-host Kubernetes replication verifies host separation using SHA-256 hashes of each host's `/etc/machine-id`. The raw machine-ID strings are intentionally not retained. Private VNet InternalIP addresses (`172.16.0.x`) are retained because they document the executed cluster topology and are not public endpoints or credentials. No k3s join token, cloud credential, SSH private key or secret is included in the release.
