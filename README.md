# Topographic Maps of India

Collection of topographic maps of India from various sources, organized by scale and project.

**Website**: [https://ramseraph.github.io/india_topo_maps/](https://ramseraph.github.io/india_topo_maps/)

## 1:253k Scale - Indian Atlas

  - **Source**: Survey of India
  - **Coverage**: 308 historical editions across 121 sheet IDs
  - **Mosaic**: Quarter sheets overlay full sheets. Later editions take precedence within each extent.
  - [Demo/Compare](https://ramseraph.github.io/india_topo_maps/253k/indian_atlas/compare/)
  - [Browse Individual Sheets (STAC)](https://indianopenmaps.com/stac-viewer?collection=indian-atlas-253k)
  - [Original Scans](https://github.com/ramSeraph/india_topo_maps/releases/tag/253k-indian-atlas-orig)
  - [Georeferenced Sheets (GeoTIFFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/253k-indian-atlas-georef)
  - [PMTiles](https://github.com/ramSeraph/india_topo_maps/releases/tag/253k-indian-atlas-pmtiles)
  - [Mosaic Sheet Footprints (GeoJSON)](https://github.com/ramSeraph/india_topo_maps/releases/download/253k-indian-atlas-pmtiles/bounds.geojson)
  - [1902 Graticule Tables (PDF)](https://github.com/ramSeraph/india_topo_maps/releases/download/soi-ancillary/graticules_indian_atlas.pdf)
  - [Automatic Georeferencing and Projection Notes](253k/indian_atlas/)

## 1:50,000 Scale - Open Series Maps (OSM)
  - **Source**: Survey of India
  - **Coverage**: Most of India
  - **Updates**: Automatically updated weekly (Saturdays)
  - [Demo/Compare](https://ramseraph.github.io/india_topo_maps/50k/osm/compare)
  - [Sheet Listing](https://ramseraph.github.io/india_topo_maps/50k/osm/sheets)
  - [Extraction Status](https://ramseraph.github.io/india_topo_maps/50k/osm/status)
  - [Original Sheets (PDFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/50k-osm-orig)
  - [Georeferenced Sheets (GeoTIFFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/50k-osm-georef)
  - [JPG Images](https://github.com/ramSeraph/india_topo_maps/releases/tag/50k-osm-jpg)
  - [PMTiles](https://github.com/ramSeraph/india_topo_maps/releases/tag/50k-osm-pmtiles)
  - [Sheet Index (GeoJSON)](https://github.com/ramSeraph/india_topo_maps/releases/download/soi-ancillary/index_50k.geojson)

## 1:25,000 Scale - National Hydrology Project (NHP)
  - **Source**: Survey of India and National Hydrology Project
  - **Series**: "Flood Risk Area Map" series
  - **Coverage**: Selected areas of India
  - [Demo/Compare](https://ramseraph.github.io/india_topo_maps/25k/nhp/compare)
  - [Sheet Listing](https://ramseraph.github.io/india_topo_maps/25k/nhp/sheets)
  - [Extraction Status](https://ramseraph.github.io/india_topo_maps/25k/nhp/status)
  - [Original Sheets (PDFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-nhp-orig)
  - [Georeferenced Sheets (GeoTIFFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-nhp-georef)
  - [PMTiles](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-nhp-pmtiles)
  - [Sheet Index (GeoJSON)](https://github.com/ramSeraph/india_topo_maps/releases/download/soi-ancillary/index_25k.geojson)

## 1:25,000 Scale - Coastal Zone Management Plan (CZMP)

  - **Source**: National Centre for Sustainable Coastal Management and state coastal zone management authorities
  - **Coverage**: Coastal areas of India. The mosaic uses 1,007 sheets. Where editions share a grid cell, 31 pairs are clipped at state or union territory boundaries and seven pairs at Maharashtra district boundaries.
  - The originals release contains 1,018 files. The mosaic uses West Bengal’s 71 approved CRZ 2011 sheets. Its 11 draft CRZ 2019 JPEGs are available in the originals release.
  - [Demo/Compare](https://indianopenmaps.com/raster-viewer#left=%2Fczmp%2F25k%2Fncscm%2F&right=osm&map=13/16.75721/82.21619)
  - [Sheet Listing](https://ramseraph.github.io/india_topo_maps/25k/czmp/sheets)
  - [Browse Individual Sheets (STAC)](https://indianopenmaps.com/stac-viewer?collection=india-czmp-25k)
  - [Original Sheets](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-czmp-orig)
  - [Georeferenced Sheets (EPSG:3857 GeoTIFFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-czmp-georef)
  - [PMTiles (WebP, zooms 0–15)](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-czmp-pmtiles)
  - [Mosaic Sheet Footprints (GeoJSON)](https://github.com/ramSeraph/india_topo_maps/releases/download/25k-czmp-pmtiles/bounds.geojson)

## 1:5,000 Scale - CMPDI
  - **Source**: Survey of India and Central Mine Planning and Design Institute
  - **Coverage**: Mining areas of India
  - [Sheet Listing](https://ramseraph.github.io/india_topo_maps/5k/cmpdi/sheets)
  - [Original Sheets (PDFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/5k-cmpdi-orig)
  - [Replacement symbol fonts and reconstruction notes](5k/cmpdi/fonts/)
  - **Note**: Raw PDF files only, no georeferenced data or PMTiles available

## Using the Data

### Downloading PMTiles as MBTiles
The Indian Atlas, OSM and NHP mosaics are split across several PMTiles files. The following commands download and combine each mosaic into one MBTiles file.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Download the 253k Indian Atlas
uvx --from pmtiles-mosaic download-mosaic -u https://github.com/ramSeraph/india_topo_maps/releases/download/253k-indian-atlas-pmtiles/Indian_Atlas_253k.mosaic.json -o indian_atlas_253k.mbtiles

# Download 50k OSM
uvx --from pmtiles-mosaic download-mosaic -u https://github.com/ramSeraph/india_topo_maps/releases/download/50k-osm-pmtiles/SOI-OSM-50k.mosaic.json -o soi_osm_50k.mbtiles

# Download 25k NHP
uvx --from pmtiles-mosaic download-mosaic -u https://github.com/ramSeraph/india_topo_maps/releases/download/25k-nhp-pmtiles/SOI-NHP-25k.mosaic.json -o soi_nhp_25k.mbtiles
```

The CZMP mosaic is distributed as a [single PMTiles archive](https://github.com/ramSeraph/india_topo_maps/releases/download/25k-czmp-pmtiles/CZMP-25k.pmtiles).

### Tile URLs

- **253k Indian Atlas** `https://indianopenmaps.com/soi/253k/indian-atlas/{z}/{x}/{y}.webp`
- **50k OSM**: `https://indianopenmaps.com/soi/osm/{z}/{x}/{y}.webp`
- **25k NHP**: `https://indianopenmaps.com/soi/25k/nhp/{z}/{x}/{y}.webp`
- **25k CZMP**: `https://indianopenmaps.com/czmp/25k/ncscm/{z}/{x}/{y}.webp`

### Using with JOSM
The tile URLs can be used with JOSM after installing:
1. **ImageIO plugin** - Enable webp in Imagery Preferences → ImageIO tab
2. For local MBTiles files, also install [iandees/josm-mbtiles](https://github.com/iandees/josm-mbtiles)

## Automated Workflows

The repository uses GitHub Actions to automatically maintain and update the map data:

### Weekly Updates
- **50k OSM Scraping**: Automated weekly scraping of new Survey of India Open Series Maps (runs every Saturday)
  - Checks for new sheets
  - Downloads and processes PDFs
  - Generates georeferenced GeoTIFFs
  - Creates JPG images
  - Updates PMTiles
  - All updates are automatically released

### Monthly Keep-Alive

- [Keep scheduled workflows active](https://github.com/ramSeraph/india_topo_maps/actions/workflows/keepalive.yml) runs on the first of each month at 03:17 UTC / 08:47 IST, or manually.
- It commits a UTC timestamp to `.github/keepalive` on `main` to keep repository activity within GitHub's 60-day inactivity window.
- It uses the built-in `GITHUB_TOKEN` with `contents: write`; no extra secret is needed. Re-enable any already-disabled schedules in Actions first.

### Documentation Deployment
- **GitHub Pages**: Automatically deploys the documentation site when changes are pushed to main branch
  - Downloads current data listings from releases
  - Builds and deploys the interactive map viewers
  - Updates sheet indexes and status pages

### Workflows
All automated workflows are defined in `.github/workflows/` and run on GitHub Actions infrastructure.

## Repository Structure
- `/docs` - GitHub Pages site with interactive viewers
- `/25k`, `/50k`, `/5k` - Map data processing scripts (organized by scale)
- `.github/workflows/docs.yml` - Automated deployment workflow
