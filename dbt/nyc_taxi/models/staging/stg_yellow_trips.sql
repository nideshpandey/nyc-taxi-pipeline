{{
    config(
        materialized='incremental',
        unique_key='trip_id',
        incremental_strategy='delete+insert'
    )
}}

-- Staging: rename, cast, filter garbage.
-- Incremental: on re-runs, only rows from source files not yet in this
-- model are processed (file-partition based incrementality).

with source as (

    select * from {{ source('raw', 'yellow_trips') }}

    {% if is_incremental() %}
    where source_file not in (select distinct source_file from {{ this }})
    {% endif %}

),

cleaned as (

    select
        md5(concat_ws('|',
            source_file, tpep_pickup_datetime, tpep_dropoff_datetime,
            PULocationID, DOLocationID, total_amount
        ))                                   as trip_id,
        source_file,
        tpep_pickup_datetime                  as pickup_at,
        tpep_dropoff_datetime                 as dropoff_at,
        date_trunc('day', tpep_pickup_datetime) as pickup_date,
        cast(PULocationID as integer)         as pickup_zone_id,
        cast(DOLocationID as integer)         as dropoff_zone_id,
        cast(passenger_count as integer)      as passenger_count,
        trip_distance,
        cast(payment_type as integer)         as payment_type_id,
        fare_amount,
        tip_amount,
        tolls_amount,
        total_amount,
        datediff('second', tpep_pickup_datetime, tpep_dropoff_datetime) / 60.0
                                              as duration_min

    from source
    -- documented cleaning rules:
    where tpep_dropoff_datetime > tpep_pickup_datetime      -- no time travel
      and trip_distance > 0 and trip_distance < 200         -- plausible distance
      and total_amount > 0 and total_amount < 1000          -- plausible fare
      and passenger_count between 1 and 8

)

select * from cleaned
