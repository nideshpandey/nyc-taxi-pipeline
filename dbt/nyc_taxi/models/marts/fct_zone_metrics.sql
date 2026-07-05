-- Zone mart at (pickup_date, zone) grain so the dashboard can filter
-- top-zone rankings by date range and borough. ~265 zones x days = small.

with trips as (
    select * from {{ ref('stg_yellow_trips') }}
),

zones as (
    select * from {{ ref('taxi_zone_lookup') }}
)

select
    t.pickup_date,
    coalesce(z.Borough, 'Unknown')  as borough,
    coalesce(z.Zone, 'Unknown')     as zone,
    count(*)                        as pickups,
    sum(t.total_amount)             as revenue,
    sum(t.tip_amount)               as tip_sum,
    sum(t.fare_amount)              as fare_sum
from trips t
left join zones z on t.pickup_zone_id = z.LocationID
group by 1, 2, 3
