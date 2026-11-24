// Dataset settings for the OpenLayers comparison used by the 50k demo.
window.sheetCompareSettings = {
    center: [78.4, 26.3],
    zoom: 6,
    nativeMaxZoom: 13,
    tileUrl: 'https://indianopenmaps.com/soi/253k/indian-atlas/{z}/{x}/{y}.webp',
    attribution: 'Survey of India. Scans by ' +
        makeLink('https://doi.org/10.5281/zenodo.19431985', 'John Brown') + ' (' +
        makeLink('https://creativecommons.org/licenses/by/4.0/', 'CC BY 4.0') + ').',
    gridTitle: 'Sheet footprints',
    gridUrl: '253k/indian_atlas/bounds.geojson',
    gridAttribution: makeLink('https://github.com/ramSeraph/india_topo_maps/releases/tag/253k-indian-atlas-pmtiles', 'Indian Atlas mosaic footprints'),
    overlappingSheets: true,
    sheetPopup(features) {
        const list = document.createElement('ul');
        // The renderer draws higher editions on top. List them in the same order.
        for (const f of features.sort((a, b) => b.get('draw_order') - a.get('draw_order'))) {
            const item = document.createElement('li');
            const link = document.createElement('a');
            link.href = 'https://github.com/ramSeraph/india_topo_maps/releases/download/253k-indian-atlas-georef/' +
                encodeURIComponent(f.get('filename'));
            link.textContent = f.get('archive_filename');
            item.append(link);
            list.append(item);
        }
        return list;
    }
};
