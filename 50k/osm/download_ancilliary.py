# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "soi-common",
# ]
#
# [tool.uv.sources]
# soi-common = { git = "https://github.com/ramseraph/soi_common" }
# ///

import logging

from pprint import pformat
from pathlib import Path

from bs4 import BeautifulSoup

from soi_common.login import get_form_data
from soi_common.common import (
    base_url,
    setup_logging,
    get_page_soup,
    ensure_dir,
    session,
    raw_data_dir
)

logger = logging.getLogger(__name__)
        
def get_map_index_form_data(soup):
    form_data = {}
    form_data['ctl00$ContentPlaceHolder1$rblFreeProduct'] = '1'
    form_data['ctl00$ContentPlaceHolder1$gvFreeProduct$ctl02$btnDownloadMap'] = 'Click to Download'
    return form_data


def download_index_file():
    out_file = raw_data_dir + 'OSM_SHEET_INDEX.zip'
    if Path(out_file).exists():
        logger.info(f'{out_file} exists.. skipping')
        return out_file
    url = base_url + 'FreeOtherMaps.aspx'
    resp = session.get(url)
    if not resp.ok:
        raise Exception('unable to get FreeOtherMaps page')
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update(get_map_index_form_data(soup))
    logger.debug(f'index file form data:\n{pformat(form_data)}')
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    resp = session.post(url, data=form_data, headers=headers)
    logger.debug(f'status_code = {resp.status_code} headers:\n{pformat(dict(resp.headers))}')
    if not resp.ok:
        raise Exception('FreeOtherMaps failed')
    ensure_dir(out_file)
    logger.info(f'writing file {out_file}')
    with open(out_file, 'wb') as f:
        f.write(resp.content)
    return out_file


def get_fonts():
    out_file = Path('data/raw/SOI_FONTS.zip')
    if out_file.exists():
        return

    url = base_url + '/SOIFonts.aspx'
    soup = get_page_soup(url)
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$btnSOIFonts': 'Click here to Download SOI Fonts.'
    })
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    resp = session.post(url, data=form_data, headers=headers)
    logger.debug(f'status_code = {resp.status_code} headers:\n{pformat(dict(resp.headers))}')
    if not resp.ok:
        raise Exception('unable to download fonts zip')

    if resp.headers['Content-Type'] != 'text/html; charset=utf-8':
        content = resp.content
    else:
        with open('failed.html', 'w') as f:
            f.write(resp.text)
        logger.error(f'status_code = {resp.status_code} headers:\n{pformat(dict(resp.headers))}')
        logger.error(resp.text)
        raise Exception('Expected zip got html')

    logger.info('writing fonts file')
    Path(out_file).parent.mkdir(exist_ok=True, parents=True)
    with open(out_file, 'wb') as f:
        f.write(content)
 
if __name__ == '__main__':
    setup_logging(logging.INFO)
    download_index_file()
    get_fonts()
