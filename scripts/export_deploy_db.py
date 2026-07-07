# scripts/export_deploy_db.py  (run from the project root)
import duckdb

con = duckdb.connect("dashboard/deploy.duckdb")  # created if missing
con.execute(
    "ATTACH 'data/warehouse/nyc_taxi.duckdb' AS src (READ_ONLY)"
)
con.execute("CREATE SCHEMA IF NOT EXISTS main_marts")
for t in ["fct_trip_summary", "fct_zone_metrics"]:
    con.execute(
        f"CREATE OR REPLACE TABLE main_marts.{t} AS "
        f"SELECT * FROM src.main_marts.{t}"
    )
    n = con.execute(f"SELECT count(*) FROM main_marts.{t}").fetchone()[0]
    print(f"exported {t}: {n:,} rows")
con.close()
print("wrote dashboard/deploy.duckdb")