# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "soi-common",
#     "torch; sys_platform == 'linux'",
#     "torchvision; sys_platform == 'linux'",
# ]
#
# [tool.uv.sources]
# soi-common = { git = "https://github.com/ramseraph/soi_common", rev = "5ac714f5e0b2e6d741da8da97951702dd70f59b9" }
# torch = { index = "pytorch-cpu", marker = "sys_platform == 'linux'" }
# torchvision = { index = "pytorch-cpu", marker = "sys_platform == 'linux'" }
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
# ///

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time

from bs4 import BeautifulSoup
import requests

from soi_common.common import base_url, get_form_data, session
from nhp_portal import get_product_selection, normalize_sheet_no, require_pdf_picker

logger = logging.getLogger(__name__)
PREFIX = 'ctl00$ContentPlaceHolder1$'
DELAY = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def request(client, method, url, **kwargs):
    for attempt in range(3):
        time.sleep(DELAY)
        try:
            response = client.request(method, url, timeout=(20, 90), **kwargs)
            response.raise_for_status()
            if response.url.endswith(('Errorpage.aspx', 'Login.aspx')):
                raise RuntimeError(f'SOI redirected the catalogue lookup to {response.url}')
            return response
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def post_page(client, url, soup, updates):
    data = get_form_data(soup)
    data.update(updates)
    response = request(client, 'POST', url, data=data, headers={'Referer': url})
    return response.url, BeautifulSoup(response.text, 'html.parser')


def open_product(client):
    url = base_url + 'Digital_Product_Show.aspx'
    response = request(client, 'GET', url)
    soup = BeautifulSoup(response.text, 'html.parser')
    url, soup = post_page(client, url, soup, {
        PREFIX + 'rblDigitalProduct': '12', PREFIX + 'rblFormats': 'All',
        '__EVENTTARGET': PREFIX + 'rblDigitalProduct$3',
    })
    selection = get_product_selection(soup)
    selection.update({PREFIX + 'rblDigitalProduct': '12', PREFIX + 'rblFormats': 'All'})
    url, soup = post_page(client, url, soup, selection)
    require_pdf_picker(soup)
    return url, soup


def open_listing(client):
    url, soup = open_product(client)
    url, soup = post_page(client, url, soup, {
        PREFIX + 'ddlFormateTyoe': 'pdf', PREFIX + 'txtSheetNumber': '',
        PREFIX + 'ddlstate': '0', PREFIX + 'ddldist': '0',
        '__EVENTTARGET': PREFIX + 'ddlFormateTyoe',
    })
    return post_page(client, url, soup, {
        PREFIX + 'ddlFormateTyoe': 'pdf', PREFIX + 'txtSheetNumber': '',
        PREFIX + 'ddlstate': '0', PREFIX + 'ddldist': '0',
        '__EVENTTARGET': PREFIX + 'lbtnSheetNumber',
    })


def parse_sheet_page(soup, page_number):
    table = soup.find('table', id='ContentPlaceHolder1_GridView1')
    if table is None:
        raise RuntimeError('SOI returned no sheet-list table')
    sheets = [normalize_sheet_no(s.get_text(strip=True))
              for s in table.find_all('span', id=re.compile(r'_lblsheetno_\d+$'))]
    if not sheets and 'data not found' not in table.get_text(' ', strip=True).lower():
        raise RuntimeError('SOI returned an unrecognized sheet-list table')
    pager = table.find('tr', class_='grid-pager')
    if pager is None:
        if page_number != 1:
            raise RuntimeError('SOI lost the sheet-list pagination')
        return sheets, None
    current = [int(s.get_text(strip=True)) for s in pager.find_all('span')
               if s.get_text(strip=True).isdigit()]
    if current != [page_number]:
        raise RuntimeError(f'SOI returned page {current}, expected {page_number}')
    pages = set()
    for link in pager.find_all('a', href=True):
        match = re.search(r"'Page\$(\d+)'", link['href'])
        if match:
            pages.add(int(match[1]))
    if page_number + 1 in pages:
        return sheets, page_number + 1
    if any(p > page_number for p in pages):
        raise RuntimeError('SOI pager would skip one or more pages')
    return sheets, None


def new_client():
    client = requests.Session()
    client.headers.update(session.headers)
    client.proxies.update(session.proxies)
    return client


def safe_name(name):
    return re.sub(r'[^A-Za-z0-9 _.-]', '_', name).strip(' .') or 'unnamed'


def scrape_state(state_id, state_name, output_dir, refresh=False):
    records = []
    with new_client() as client:
        url, soup = open_listing(client)
        listing_soup = soup
        product = soup.find('input', id='ContentPlaceHolder1_hdnproductsCode')['value']
        response = request(client, 'POST', url + '/GetDistrictlist',
                           json={'stateId': state_id, 'ProductCode': product})
        districts = response.json()['d']
        logger.info('%s: %d districts', state_name, len(districts))
        for district in districts:
            district_id, district_name = district['DistrictID'], district['DistrictName']
            relative = Path(safe_name(state_name)) / safe_name(district_name) / 'sheets.txt'
            target = output_dir / relative
            metadata_file = target.with_name('metadata.json')
            if not refresh and target.exists() and metadata_file.exists():
                record = json.loads(metadata_file.read_text())
                if record['sheet_count'] == len(set(target.read_text().splitlines())):
                    records.append(record)
                    continue
            # The website populates these hidden fields in its change handlers.
            fields = {
                PREFIX + 'ddlFormateTyoe': 'pdf', PREFIX + 'txtSheetNumber': '',
                PREFIX + 'ddlstate': state_id, PREFIX + 'ddldist': district_id,
                PREFIX + 'ddlProductsType': 'pdf',
                PREFIX + 'hdnddlstateID': state_id, PREFIX + 'hdnddlstateName': state_name,
                PREFIX + 'HdnddldistID': district_id, PREFIX + 'HdnddldistName': district_name,
            }
            # Start each district from the unselected format/page state. Reusing
            # the previous PDF page does not trigger SelectedIndexChanged and
            # silently returns the previous district's rows and page number.
            url, soup = post_page(client, url, listing_soup, {
                **fields, '__EVENTTARGET': PREFIX + 'ddlProductsType',
            })
            sheets = set()
            page = 1
            while True:
                page_sheets, next_page = parse_sheet_page(soup, page)
                sheets.update(page_sheets)
                if next_page is None:
                    break
                url, soup = post_page(client, url, soup, {
                    **fields, '__EVENTTARGET': PREFIX + 'GridView1',
                    '__EVENTARGUMENT': f'Page${next_page}',
                })
                page = next_page
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_text(''.join(s + '\n' for s in sorted(sheets)))
            temporary.replace(target)
            record = {'state': state_name, 'district': district_name,
                      'state_id': state_id, 'district_id': district_id,
                      'file': str(relative), 'sheet_count': len(sheets),
                      'pages': page, 'fetched_at': utc_now()}
            metadata_file.write_text(json.dumps(record, indent=2) + '\n')
            records.append(record)
            logger.info('%s / %s: %d sheets (%d pages)', state_name, district_name, len(sheets), page)
    return records


def scrape(output_dir=Path('data/list_current'), workers=2, refresh=False, state_names=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'complete': False, 'filtered': bool(state_names),
                'started_at': utc_now(), 'districts': [], 'errors': []}
    manifest_file = output_dir / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
    with new_client() as client:
        _, soup = open_listing(client)
        states = {o['value']: o.get_text(strip=True)
                  for o in soup.find('select', id='ContentPlaceHolder1_ddlstate').find_all('option')
                  if o.get('value') not in ('', '0')}
    if state_names:
        requested = {s.upper() for s in state_names}
        missing = requested - set(states.values())
        if missing:
            raise ValueError(f'States not offered by SOI: {sorted(missing)}')
        states = {k: v for k, v in states.items() if v in requested}
    manifest['states'] = states
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scrape_state, k, v, output_dir, refresh): v
                   for k, v in states.items()}
        for future in as_completed(futures):
            state = futures[future]
            try:
                manifest['districts'].extend(future.result())
                logger.info('Completed state: %s', state)
            except Exception as exc:
                logger.exception('Failed state: %s', state)
                manifest['errors'].append({'state': state, 'error': str(exc)})
            manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
    manifest['complete'] = not manifest['errors']
    manifest['finished_at'] = utc_now()
    manifest['districts'].sort(key=lambda d: (d['state'], d['district']))
    manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
    if manifest['errors']:
        raise RuntimeError('Catalogue refresh incomplete; rerun to resume completed districts')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Refresh NHP PDF availability by state and district')
    parser.add_argument('--output-dir', type=Path, default=Path('data/list_current'))
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--refresh', action='store_true', help='Refetch completed districts')
    parser.add_argument('--state', action='append', help='Limit to a named state (repeatable)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    scrape(args.output_dir, args.workers, args.refresh, args.state)
