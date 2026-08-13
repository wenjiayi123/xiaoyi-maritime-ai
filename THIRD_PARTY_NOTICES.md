# Third-party notices

## UCI Appliances Energy Prediction

The file `data/public/uci_appliances_energy.csv` is a column-selected and
unit-converted derivative of:

- Title: Appliances Energy Prediction
- Creator: Luis Candanedo
- Publisher: UCI Machine Learning Repository
- DOI: <https://doi.org/10.24432/C5VC8G>
- Source: <https://archive.ics.uci.edu/dataset/374/appliances+energy+prediction>
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)

The exact download URL, source archive SHA-256, derived CSV SHA-256 and
transformations are recorded in
`data/public/uci_appliances_energy.provenance.json`.

## UCI Individual Household Electric Power Consumption

The file `data/public/uci_household_power_5min.csv` is a five-minute aggregation of
published one-minute active-power measurements from:

- Title: Individual Household Electric Power Consumption
- Creators: Georges Hebrail and Alice Berard
- Publisher: UCI Machine Learning Repository
- DOI: <https://doi.org/10.24432/C58K54>
- Source: <https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption>
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)

The source and derived hashes, skipped missing values, aggregation method, and row
counts are recorded in `data/public/uci_household_power_5min.provenance.json`.

## NOAA MarineCadastre historical AIS

The file `data/public/noaa_la_lb_ais_2024_12_25_1min.csv` is derived from the
U.S. Coast Guard Nationwide AIS point data published through NOAA Office for
Coastal Management and the Bureau of Ocean Energy Management:

- Landing page: <https://coast.noaa.gov/digitalcoast/tools/ais.html>
- Archive directory: <https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2024/>
- Notice: U.S. Government material; public-use and disclaimer terms are recorded
  in the adjacent provenance file.

The committed derivative filters to the declared Los Angeles–Long Beach bounding
box and aggregates unique MMSI, navigation status, speed, and vessel type into
observed one-minute buckets. It is not suitable for enforcement. Exact source URL,
transformations, bounds, row counts, and hashes are recorded in
`data/public/noaa_la_lb_ais_2024_12_25_1min.provenance.json`.

## Maritime knowledge references

Files under `data/kb/` are project-authored summaries, indexes, question-answer
material and source locators. They are not bundled copies of the external
standards, conventions, regulations or publisher pages they reference. Each
document's institution, URL, verification level, content scope and publisher
terms are registered in `data/source_registry.json`.

The MIT license for this repository does not grant rights to third-party
standards, laws, webpages, trademarks or external documents. Users must follow
the applicable publisher terms before fetching, storing or redistributing any
external full text.

## Project visual assets

The repository-local provenance and redistribution status of raster visual
assets is recorded in `data/assets/asset_registry_v1.json`. On 2026-08-14 the
authenticated repository owner explicitly approved GitHub publication of the
pre-existing Xiaoyi Q-style hero artwork and screenshots containing it. That
approval is limited to redistribution as part of this repository. Copyright is
not transferred, and the repository MIT license must not be interpreted as a
standalone license to extract, reuse, or redistribute the character artwork.
