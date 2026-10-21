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

"""Refresh the SOI preview index, catalogue, and inventory; rebuild retry sheets."""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import re
from urllib.parse import urljoin
import zipfile

import build_download_list as lists
import scrape_available as catalogue

logger = logging.getLogger(__name__)
PUBLISHED_URL = 'https://github.com/ramSeraph/india_topo_maps/releases/download/25k-nhp-orig/listing_files.csv'


def save_validated(response, path, reader):
    """Keep the previous input if a successful HTTP response contains an error page."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    try:
        temporary.write_bytes(response.content)
        result = reader(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    metadata = {
        'downloaded_at': catalogue.utc_now(), 'file': str(path.resolve()),
        'bytes': len(response.content), 'sha256': hashlib.sha256(response.content).hexdigest(),
        'content_disposition': response.headers.get('Content-Disposition'),
    }
    return result, metadata


def validate_index(path):
    if not zipfile.is_zipfile(path):
        raise ValueError('SOI preview index response is not a ZIP archive')
    return lists.read_index(path)


def validate_inventory(path):
    sheets = lists.read_published(path)
    if not sheets:
        raise ValueError('Published inventory contains no PDFs')
    return sheets


def download_index(path):
    with catalogue.new_client() as client:
        url, soup = catalogue.open_product(client)
        links = [link for link in soup.find_all('a', href=True)
                 if 'download preview index' in ' '.join(link.get_text(' ', strip=True).lower().split())]
        if len(links) != 1:
            raise RuntimeError(f'Expected one NHP Download Preview Index link, found {len(links)}')
        href = links[0]['href']
        event_target = None
        if href.lower().startswith('javascript:'):
            match = re.fullmatch(r'''javascript:__doPostBack\(['"]([^'"]+)['"],\s*['"]([^'"]*)['"]\);?''', href)
            if match is None:
                raise RuntimeError('Unrecognized SOI preview index download action')
            event_target = match[1]
            form = catalogue.get_form_data(soup)
            form.update({'__EVENTTARGET': match[1], '__EVENTARGUMENT': match[2]})
            response = catalogue.request(client, 'POST', url, data=form, headers={'Referer': url})
        else:
            response = catalogue.request(client, 'GET', urljoin(url, href), headers={'Referer': url})
        (sheets, entries), metadata = save_validated(response, path, validate_index)
        metadata.update({'product_page': url, 'event_target': event_target,
                         'download_url': response.url, 'sheets': len(sheets), 'entries': entries})
        logger.info('Downloaded SOI preview index: %s sheets', len(sheets))
        return metadata


def download_inventory(path):
    with catalogue.new_client() as client:
        response = catalogue.request(client, 'GET', PUBLISHED_URL)
        sheets, metadata = save_validated(response, path, validate_inventory)
        # Record the stable release URL, not GitHub's temporary signed redirect.
        metadata.update({'source_url': PUBLISHED_URL, 'sheets': len(sheets)})
        logger.info('Downloaded published inventory: %s PDFs', len(sheets))
        return metadata


def refresh(data_dir=Path('data'), reuse_catalogue=False, workers=2):
    data_dir = Path(data_dir)
    catalogue_dir = data_dir / 'list_current'
    if reuse_catalogue:
        # Reject incomplete/filtered caches before making any network requests.
        lists.read_catalogue(catalogue_dir)
    index_path = data_dir / 'NHP_3_5m.zip'
    published_path = data_dir / 'listing_files.csv'
    sources = {'index': download_index(index_path), 'published': download_inventory(published_path)}
    (data_dir / 'lookup_sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    if not reuse_catalogue:
        # A new check must refetch every district, including prior empty results.
        # On failure, build() is never called and the previous retry list survives.
        catalogue.scrape(catalogue_dir, workers=workers, refresh=True)
    summary = lists.build(index_path, catalogue_dir, published_path, data_dir / 'raw', data_dir)
    summary['sources'] = sources
    summary['catalogue_reused'] = reuse_catalogue
    (data_dir / 'sheet_availability_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    logger.info('Wrote %s retry sheets to %s', summary['to_lookup'], data_dir / 'sheet_nos_to_lookup.txt')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--reuse-catalogue', action='store_true',
                        help='Reuse a complete catalogue; still download the current index and published inventory')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print(json.dumps(refresh(args.data_dir, args.reuse_catalogue, args.workers), indent=2))
