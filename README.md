# Topographic Maps of India

Collection of topographic maps of India from various sources, organized by scale and project.

**Website**: [https://ramseraph.github.io/india_topo_maps/](https://ramseraph.github.io/india_topo_maps/)

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
  - **Source**: Coastal Zone Management Plan
  - **Coverage**: Coastal areas of India
  - [Sheet Listing](https://ramseraph.github.io/india_topo_maps/25k/czmp/sheets)
  - [Original Sheets (PDFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-czmp-orig)
  - **Note**: Raw PDF files only, no georeferenced data or PMTiles available

## 1:5,000 Scale - CMPDI
  - **Source**: Survey of India and Central Mine Planning and Design Institute
  - **Coverage**: Mining areas of India
  - [Sheet Listing](https://ramseraph.github.io/india_topo_maps/5k/cmpdi/sheets)
  - [Original Sheets (PDFs)](https://github.com/ramSeraph/india_topo_maps/releases/tag/5k-cmpdi-orig)
  - **Note**: Raw PDF files only, no georeferenced data or PMTiles available

## Using the Data

### Downloading PMTiles as MBTiles
For projects with PMTiles support (OSM 50k and NHP 25k), you can download the data as MBTiles:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Download 50k OSM
uvx --from pmtiles-mosaic download-mosaic -u https://github.com/ramSeraph/india_topo_maps/releases/download/50k-osm-pmtiles/SOI-OSM-50k.mosaic.json -o soi_osm_50k.mbtiles

# Download 25k NHP
uvx --from pmtiles-mosaic download-mosaic -u https://github.com/ramSeraph/india_topo_maps/releases/download/25k-nhp-pmtiles/SOI-NHP-25k.mosaic.json -o soi_nhp_25k.mbtiles
```

### Tile URLs
- **50k OSM**: `https://indianopenmaps.fly.dev/soi/osm/{z}/{x}/{y}.webp`
- **25k NHP**: `https://indianopenmaps.fly.dev/soi/25k/nhp/{z}/{x}/{y}.webp`

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
