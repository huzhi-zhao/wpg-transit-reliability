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

The work follows CRISP-DM: business and data understanding were settled by the
feasibility check. The first version is deliberately small. It takes one route in
one direction and covers data understanding, data preparation, modeling and
evaluation; deployment comes later.

1. **Records.** The City of Winnipeg publishes, for every bus departing every
   stop, the scheduled time and the deviation from it in seconds. The archive
   reaches back to July 2017; the first version uses records from after the
   July 2025 network redesign.
2. **One route, one direction.** Route 91 towards St. Norbert: 16 stops, weekday
   departures scheduled before 18:00, about 80,000 rows. It was chosen on data
   quality alone: its timetable did not change over the period, and it has
   essentially no erroneous records.
3. **Departures.** A departure is identified by its stop and scheduled time. That
   is enough to find the same departure on every past weekday, without the
   published schedule.
4. **Features.** Everything is limited to what is known the day before. From the
   records themselves: time of day and week, the stop, the
   departure's own history, and how late buses on the route have been running
   over the last few days. Four small outside tables are joined in during data
   preparation: daily weather (the previous day's), statutory holidays, snow
   parking bans, and average boardings per stop.
5. **Model and evaluation.** A historical-frequency baseline, a linear model and a
   tree model each predict the chance that a departure is more than a set number
   of seconds late, or early. They are compared on a later stretch of time that
   none of them was trained on, using calibration (does "80%" come true about
   80% of the time).

More routes, any deadline the rider chooses, an ensemble of models, a query
tool, joining the records to the published schedule, weather forecasts, road
work and school calendars all come after the first version.

## Current scope

The feasibility check is complete and the project goes ahead; no pipeline or
model exists yet. Records from autumn 2026 and winter 2025-26 were joined to the
published schedules of their periods: over 99.9% of records match a trip, and
roughly 62-70% of scheduled daytime trips appear in the records. Missing trips
go missing as whole vehicle duties rather than as late buses, and evening trips
are recorded far less often than daytime ones. On the worst winter days a few
more trips go missing, while the ones recorded run later than usual, so bad days
are somewhat under-represented in the history.

The first version produces, for one route in one direction (route 91 towards
St. Norbert, weekday departures scheduled before 18:00, records from after the
2025 network redesign), the probability that a departure runs late or leaves
early by more than a fixed margin, and an honest evaluation of those
probabilities. On this route some whole days have no records, which the data
preparation has to handle. Results hold for this route only. Everything else
comes after it.
