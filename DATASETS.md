# Data strategy and dataset cards

ScamTrace has two separate research tracks. Results from the tracks must never be presented as though they came from the same source.

## Track A: real transaction-level benchmark

**ULB / Worldline Credit Card Fraud Detection**

- Source: [OpenML dataset 1597](https://www.openml.org/d/1597), collected through a research collaboration between Worldline and the ULB Machine Learning Group.
- Content: real, anonymized European card transactions over two days in September 2013; 284,807 transactions and 492 fraud labels in the source description.
- Available features: PCA-transformed `V1`–`V28`, `Amount`, elapsed `Time` where present, and binary `Class` label.
- Good for: rare-event classification, temporal validation, ranking quality, and investigator workload measures such as precision at top K.
- Not good for: reconstructing account networks, identifying participating banks, or proving cross-bank money movement. Source attributes are anonymized and largely removed.
- Access: fetched on demand from OpenML; the raw file is stored locally under `data/raw/` and excluded from version control.
- Attribution and handling: credit Worldline and the ULB Machine Learning Group. Review the dataset's current terms before redistribution or external release. Do not attempt to re-identify people.

## Track B: multi-institution graph benchmark

**IBM AMLSim**

- Source: [IBM/AMLSim](https://github.com/IBM/AMLSim), Apache-2.0 software repository with generated sample banking networks.
- Content: synthetic accounts, transactions, banks, and known laundering typologies designed to benchmark graph and AML algorithms.
- Good for: cross-bank graph construction, path tracing, typology detection, and measuring whether graph features add value over simple transaction rules.
- Not real customer activity. Label all results as synthetic simulation results.

## Why two tracks

Public real fraud datasets generally remove account and institution identifiers. Public datasets with rich account-to-account graphs are commonly synthetic. Combining them directly would create fake links, so ScamTrace will evaluate transaction scoring on Track A and graph tracing on Track B until an authorized partner supplies compatible, governed data.

## Evaluation principles

- Keep a chronological holdout where timestamps allow; never randomly mix future activity into training when evaluating transaction monitoring.
- Report precision-recall metrics and precision/recall at investigator review capacity; raw accuracy is misleading with rare fraud.
- Compare a simple threshold baseline with a trained model and, separately, compare transaction-only versus graph features on AMLSim.
- Keep labels out of investigator-facing features. Use labels only in offline evaluation.
- Record dataset version, source, access date, transformations, split boundaries, and metrics for every run.
- Describe outputs as research signals, not verified fraud determinations or payment instructions.
