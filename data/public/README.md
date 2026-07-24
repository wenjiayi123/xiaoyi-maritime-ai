# Public RL benchmark data

Run `python scripts/fetch_public_rl_dataset.py` to reproduce the bundled CSV from
the fixed UCI download. The generated provenance JSON records the source archive
hash, derived file hash, row count and transformations.

The default dataset is **not port operational data**. It is a real, openly
licensed building-energy time series used to verify that training, progress,
model artifacts and holdout evaluation are genuine. A port deployment supplies
the same `timestamp,load_kw,...` contract through `XIAOYI_RL_DATASET_PATH`.
