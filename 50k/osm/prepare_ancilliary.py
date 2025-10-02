# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "soi-common",
# ]
#
# [tool.uv.sources]
# soi-common = { git = "https://github.com/ramseraph/soi_common" }
# ///


import os
import glob
import json
import logging
import shutil
import zipfile

from pathlib import Path
from functools import cmp_to_key
from soi_common.common import (
    setup_logging,
    data_dir
)

logger = logging.getLogger(__name__)

def unzip_file(zip_filename):
    target_dir = Path(zip_filename).parent
    logger.info(f'unzipping {zip_filename} to {target_dir}')
    with zipfile.ZipFile(zip_filename, 'r') as zip_ref:
        zip_ref.extractall(target_dir)

    extracted_dir = zip_filename.replace('.zip', '/')
    return extracted_dir


def adjust_coordinates(f):
    coords = f['geometry']['coordinates'][0][:-1]
    coords = [ [round(c[0], 2), round(c[1], 2)] for c in coords ]
    indices = range(0,4)
    def cmp(ci1, ci2):
        c1 = coords[ci1]
        c2 = coords[ci2]
        if c1[0] == c2[0]:
            return c1[1] - c2[1]
        else:
            return c1[0] - c2[0]

    #print(f'{coords=}')
    s_indices = sorted(indices, key=cmp_to_key(cmp))
    #print(s_indices)
    lb = s_indices[0]
    lt = (lb + 1) % 4
    rt = (lb + 2) % 4
    rb = (lb + 3) % 4
    out_coords = [ coords[lt], coords[lb], coords[rb], coords[rt], coords[lt] ]
    #print(f'{out_coords=}')
    f['geometry']['coordinates'] = [ out_coords ]


def correct_index_file(out_filename):
    with open(out_filename, 'r') as f:
        index_data = json.load(f)

    corrections_file = Path(__file__).parent.joinpath('index.geojson.corrections')
    with open(corrections_file, 'r') as f:
        index_corrections_data = json.load(f)

    corrections_map = {f['properties']['EVEREST_SH']:f for f in index_corrections_data['features']}

    for f in index_data['features']:
        sheet_no = f['properties']['EVEREST_SH']
        f['properties']['id'] = sheet_no.replace('/', '_')
        del f['properties']['EVEREST_SH']

        if sheet_no not in corrections_map:
            continue
        geom_correction = corrections_map[sheet_no]['geometry']
        f['geometry'] = geom_correction

    for f in index_data['features']:
        adjust_coordinates(f)

    out_filename_new = out_filename + '.new'
    with open(out_filename_new, 'w') as f:
        json.dump(index_data, f, indent=4)
    shutil.move(out_filename_new, out_filename)


def convert_shp_to_geojson(unzipped_folder, out_filename):
    filenames = glob.glob(str(Path(unzipped_folder).joinpath('*.shp')))
    assert len(filenames) == 1, f'{list(filenames)}'
    shp_file = filenames[0]
    os.system(f'ogr2ogr -f GeoJSON -t_srs EPSG:4326 {out_filename} {shp_file}')
    correct_index_file(out_filename)


if __name__ == "__main__":
    setup_logging(logging.INFO)

    logger.info('Preparing ancilliary data...')

    logger.info('Preparing OSM sheet index...')
    filename = data_dir + 'index.geojson'
    raw_filename = data_dir + 'OSM_SHEET_INDEX.zip'
    unzipped_folder = unzip_file(raw_filename)
    filename = data_dir + 'index_50k.geojson'
    convert_shp_to_geojson(unzipped_folder, filename)
    shutil.rmtree(unzipped_folder)

    logger.info('Preparing font data...')
    raw_filename = data_dir + 'SOI_FONTS.zip'
    unzipped_folder = unzip_file(raw_filename)
    logger.info(f'Fonts unzipped to {unzipped_folder}')


