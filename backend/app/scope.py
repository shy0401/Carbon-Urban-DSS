"""Comparable denominators across observed months and fuels, never all OSM area."""
from collections import defaultdict
from math import isfinite

def matched_areas(rows):
    groups=defaultdict(lambda:defaultdict(dict));invalid=set()
    for r in rows:
        if not r.grid_id or r.usage_kwh is None:continue
        raw=r.raw_record or {};code=raw.get('kapt_code');area=raw.get('matched_gross_floor_area_m2')
        if r.match_method!='KAPT_COMPLEX_CENTROID' or not code or not isinstance(area,(int,float)) or not isfinite(area) or area<=0:
            invalid.add(r.grid_id);continue
        group=groups[r.grid_id][(r.use_ym,r.energy_type)]
        if code in group:invalid.add(r.grid_id)
        group[code]=area
    result={}
    for grid,months in groups.items():
        values=list(months.values())
        if grid not in invalid and all(v==values[0] for v in values):result[grid]=sum(values[0].values())
    return result
