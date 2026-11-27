# Winnipeg Transit Reliability

**Will tomorrow's 7:46 bus get me there by 9:00?**

This project estimates, for a single scheduled bus trip, the probability that it
reaches a rider's stop by a deadline the rider chooses, and the risk that it
leaves the boarding stop before the rider gets there. It learns from the
stop-level on-time records published by the City of Winnipeg, using only what is
known the day before. The first version uses those records for a single route in
one direction, plus daily weather, holidays, snow parking bans and stop-level
ridership; more routes, the published schedule and other conditions are added
later.

Real-time apps answer "when will the next bus come". This project answers a
planning question asked the evening before: how reliable is this particular
trip, and would an earlier trip or another route lower the risk?

**[Read the overview](docs/guide/overview.md)**

## Status

The feasibility check is complete: the data source supports per-departure
probabilities for weekday daytime service. The first version is a model for one
route in one direction (route 91 towards St. Norbert, about 80,000 rows). No
pipeline, model or application exists yet.

## Data

The primary source is the City of Winnipeg's *Transit On-Time Performance Data
Archive*: one row per bus departing one stop, with the scheduled time and the
deviation from it in seconds. As measured on 2026-11-24, the archive holds about
625 million rows from July 2017 to September 2026. Details and the measurements
behind every number are in [Data Sources](docs/dev/requirements/data-sources.md)
(Chinese).

## Documentation

| Start here | What you will learn |
|---|---|
| [Overview](docs/guide/overview.md) | The question, the approach and the current scope |
| [Documentation index](docs/README.md) | How the documentation is organized |

## License

Code is licensed under the [Apache License, Version 2.0](LICENSE). Source datasets
retain their publishers' terms; the code license does not relicense the data.
This project is independent and is not affiliated with Winnipeg Transit or the
City of Winnipeg.
