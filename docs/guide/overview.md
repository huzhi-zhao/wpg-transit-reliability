# Overview

## The question

A rider who must be somewhere at 9:00 tomorrow can look up the schedule and see a
bus that arrives at 8:41. What the schedule does not say is how often that trip
actually makes it, whether a snowfall tonight changes the odds, and whether the
bus tends to leave the rider's stop early.

This project turns those questions into numbers for one scheduled trip:

- **Arrival risk**: the probability that the trip departs the rider's
  destination stop later than the rider's deadline.
- **Missed-bus risk**: the probability that the trip leaves the boarding stop
  before the time the rider plans to be there.
- **Alternatives** (later version): the same two numbers for neighbouring trips
  and routes, so a rider can see what taking an earlier bus buys.

The forecast is made the day before, using only information available at that
time.

## How this differs from real-time apps

Winnipeg Transit and third-party apps show where buses are and when the next one
is expected. That is a short-horizon point estimate. This project produces a
probability for a trip that has not started yet, so a rider can plan the night
before. It does not track vehicles or replace real-time arrival information.

## Approach

1. **Records.** The City of Winnipeg publishes, for every bus departing every
   stop, the scheduled time and the deviation from it in seconds. The archive
   reaches back to July 2017.
2. **Trips.** The records carry no trip identifier. Joining them to the published
   GTFS schedule on route, stop and scheduled time recovers which trip each
   record belongs to and the stop's position along it.
3. **Conditions.** Weather, winter road operations, construction closures and the
   calendar are added as features, restricted to what is known the day before.
4. **Model.** Several models are trained across all routes and stops and combined
   into an ensemble. Each row is one trip at one stop; route and stop are
   features, not separate models. Predictions are stored as quantiles of the
   deviation for each trip and stop, so any deadline can be answered by lookup.
5. **Evaluation.** Probabilities are judged on calibration (does "80%" come true
   about 80% of the time) against a baseline of historical on-time frequency for
   the same route, stop and time of day, with bad-weather days examined
   separately.

## Current scope

The project is in its feasibility stage; no pipeline or model exists yet. Six
weeks of records across all 73 routes (October to November 2026) have been
joined to the published schedule: 99.9% of records match a single trip, and
about 62% of scheduled trips appear in the records at all. Missing trips go
missing as whole vehicle duties rather than as late buses, and evening trips are
recorded far less often than daytime ones. A winter check, on whether bad
weather changes which trips are recorded, is still to come.

The first version will produce arrival risk and missed-bus risk for a small set
of routes, for weekday trips that leave their first stop before 18:00 (evening
trips are recorded too sparsely to model yet), using records from after
Winnipeg Transit's 2025 network redesign. Alternatives and a rider-facing
application come after it.
