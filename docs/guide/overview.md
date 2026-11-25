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
   reaches back to July 2017; the first version uses records from after the
   July 2025 network redesign.
2. **Departures.** A rider's bus is identified by its route, direction, stop and
   scheduled time. That is enough to find the same departure on every past
   weekday, so the first version needs no other data source. The rider supplies
   the scheduled time at both the boarding stop and the destination stop.
3. **Features.** Everything is derived from the records themselves and limited to
   what is known the day before: time of day and week, route and stop, the
   departure's own history, and how late buses have been running over the last
   few days. The last of these follows changes in weather or road work, a day
   or two behind.
4. **Model.** Several models are trained across all routes and stops and combined
   into an ensemble; route and stop are features, not separate models.
   Predictions are stored as quantiles of the deviation for each scheduled
   departure, so any deadline can be answered by lookup.
5. **Evaluation.** Probabilities are judged on calibration (does "80%" come true
   about 80% of the time) against a baseline of historical on-time frequency for
   the same departure, with results reported by time of day, route and month,
   including winter.

Joining the records to the published schedule, which recovers whole trips, and
adding weather and other outside data come after the first version.

## Current scope

The feasibility check is complete and the project goes ahead; no pipeline or
model exists yet. Records from autumn 2026 and winter 2025-26 were joined to the
published schedules of their periods: over 99.9% of records match a trip, and
roughly 62-70% of scheduled daytime trips appear in the records. Missing trips
go missing as whole vehicle duties rather than as late buses, and evening trips
are recorded far less often than daytime ones. On the worst winter days a few
more trips go missing, while the ones recorded run later than usual, so bad days
are somewhat under-represented in the history.

The first version will produce arrival risk and missed-bus risk for a small set
of routes, for weekday departures scheduled before 18:00 (evening buses are
recorded too sparsely to model yet), using the on-time records alone from after
Winnipeg Transit's 2025 network redesign. Alternatives, schedule and weather
data, and a rider-facing application come after it.
