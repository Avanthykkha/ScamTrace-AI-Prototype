# Raw data directory

Keep downloaded datasets here locally. Do not commit raw financial data or credentials.

The first real benchmark is the **ULB / Worldline Credit Card Fraud Detection** dataset, accessed through OpenML dataset 1597. It contains real anonymized card transactions, but only PCA-transformed features (`V1`–`V28`), amount, and a fraud label. It has no bank identifier or account-to-account transfer edges, so it is for transaction-level model evaluation only.

Run `python scripts/fetch_ulb.py` from the project root to fetch it. Credit the Machine Learning Group at Université Libre de Bruxelles and Worldline; see the dataset page and terms before redistributing any data.

The app's multi-bank trace scenario remains synthetic until an authorized data partner can provide governed cross-institution signals.
