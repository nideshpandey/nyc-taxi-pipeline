{{
    config(
        materialized='incremental',
        unique_key='pickup_date',
        incremental_strategy='delete+insert'
    )
}}

-- Filterable summary "cube": one row per
--   (pickup_date, hour_of_day, day_of_week, borough, payment_type).
-- Small enough to stay fast (~a few hundred k rows/year), rich enough
-- that the dashboard can slice by date, borough and payment type.
--
-- Metrics are stored as SUMS + COUNTS (not averages) so the dashboard
-- can recompute correct weighted averages AFTER filtering.

with trips as (

    select * from {{ ref('stg_yellow_trips') }}

    {% if is_incremental() %}
    -- rebuild only recent days (covers late-arriving / revised data)
    where pickup_date >= (select max(pickup_date) - interval 7 day from {{ this }})
    {% endif %}

),

zones as (
    select * from {{ ref('taxi_zone_lookup') }}
)

select
    t.pickup_date,
    hour(t.pickup_at)                          as hour_of_day,
    dayofweek(t.pickup_at)                     as day_of_week,   -- 0 = Sunday
    coalesce(z.Borough, 'Unknown')             as pickup_borough,
    case t.payment_type_id
        when 1 then 'Credit card'
        when 2 then 'Cash'
        when 3 then 'No charge'
        when 4 then 'Dispute'
        else 'Other'
    end                                        as payment_type,
    count(*)                                   as trips,
    sum(t.total_amount)                        as revenue,
    sum(t.fare_amount)                         as fare_sum,
    sum(t.tip_amount)                          as tip_sum,
    sum(t.trip_distance)                       as distance_sum,
    sum(t.duration_min)                        as duration_sum
from trips t
left join zones z on t.pickup_zone_id = z.LocationID
group by 1, 2, 3, 4, 5
