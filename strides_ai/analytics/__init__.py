"""Source-independent analytics for the Charts page.

Layering (each module only talks to the one below it):
  composition.py  -- mode -> explicit ordered chart set
  cardio.py       -- pure metric functions (no DB, no provider parsing, no UI)
  aggregation.py  -- shared mechanics: weekly buckets, rolling windows, unit conversion
  adapters.py     -- DB rows -> CardioAnalyticsActivity (the only DB-row-shape-aware code)
  models.py       -- CardioAnalyticsActivity, ChartDataset variants, UnavailableReason
"""
