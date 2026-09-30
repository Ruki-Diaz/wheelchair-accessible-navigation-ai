# Prebuilt regional graphs

Enriched pedestrian graphs bundled with the application so covered areas route
without any Overpass request. `RegionalGraphCache` searches this directory
(read-only) alongside the writable cache; the smallest region enclosing a
route's bounding box wins. Override the location with
`ACCESSROUTE_PREBUILT_REGIONS_DIR`.

Each region is a `<region_id>.graphml` + `<region_id>.json` pair in the same
format as `data/cache/regions/`.

| Region | Coverage | Area | Size | Purpose |
|---|---|---|---|---|
| `reg_561da3e035ef` | S -37.788533, W 145.121745, N -37.780123, E 145.133006 | 0.92 km² | 1.9 MB | Westfield Doncaster ↔ Roseville Avenue test route (100 % terrain coverage) |
| `reg_549b69abe250` | S -37.799413, W 145.117961, N -37.774539, E 145.183211 | 15.8 km² | 15.2 MB | Wider Doncaster / Doncaster East: nearby destinations and region expansion |
| `reg_03d318127b98` | S -37.868, W 145.160, N -37.845, E 145.196 | 8.1 km² | 12.5 MB | Vermont South / Burwood East incl. Vermont South Shopping Centre (98 % terrain coverage) |

## Adding a region

Generate locally (never on Render), from `backend/`:

```bash
python -c "from pathlib import Path; from accessroute.graph.manager import DynamicGraphManager; from accessroute.graph.region import BoundingBox; from accessroute.graph.regional_cache import RegionalGraphCache; m = DynamicGraphManager(cache=RegionalGraphCache(cache_dir=Path('data/prebuilt/regions'), prebuilt_dirs=[])); G, meta, _ = m.get_graph_for_bbox(BoundingBox(south=-37.7995, west=145.1179, north=-37.7745, east=145.1833)); print(meta.region_id, meta.node_count, meta.terrain_enriched)"
```

Replace the bounding box with the area to cover. Check the printed
`terrain_enriched` is `True` before committing.
