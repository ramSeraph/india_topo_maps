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

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from bs4 import BeautifulSoup
import requests

import refresh_lookup as refresh


def response(content, url='https://example.test/product'):
    result = requests.Response()
    result.status_code = 200
    result._content = content
    result.url = url
    return result


def index_zip():
    kmz = io.BytesIO()
    with zipfile.ZipFile(kmz, 'w') as archive:
        archive.writestr('doc.kml', '<kml><Placemark><name>52G7SW</name></Placemark></kml>')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('index.kmz', kmz.getvalue())
    return data.getvalue()


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_index_post_uses_current_link_and_hidden_form_state(self):
        page = BeautifulSoup('<form id="masterform"><input type="hidden" name="__VIEWSTATE" value="fresh">'
                             '<a href="javascript:__doPostBack(\'renamed$index\',\'\')">Download Preview Index</a></form>', 'html.parser')
        path = self.root / 'index.zip'
        payload = index_zip()
        with patch.object(refresh.catalogue, 'new_client'), \
                patch.object(refresh.catalogue, 'open_product', return_value=('https://example.test/product', page)), \
                patch.object(refresh.catalogue, 'request', return_value=response(payload)) as request:
            metadata = refresh.download_index(path)
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(request.call_args.args[1], 'POST')
        self.assertEqual(request.call_args.kwargs['data']['__VIEWSTATE'], 'fresh')
        self.assertEqual(request.call_args.kwargs['data']['__EVENTTARGET'], 'renamed$index')
        self.assertEqual(metadata['sheets'], 1)
        self.assertEqual(len(metadata['sha256']), 64)

    def test_invalid_download_preserves_previous_good_input(self):
        for name, validator, bad in [('index.zip', refresh.validate_index, b'<html>error</html>'),
                                     ('listing.csv', refresh.validate_inventory, b'name,size,url\n')]:
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(b'previous good input')
                with self.assertRaises(ValueError):
                    refresh.save_validated(response(bad), path, validator)
                self.assertEqual(path.read_bytes(), b'previous good input')
                self.assertFalse(path.with_name(path.name + '.tmp').exists())

    def test_reuse_rebuilds_list_without_crawling(self):
        catalogue = self.root / 'list_current'
        catalogue.mkdir()
        (catalogue / 'sheets.txt').write_text('52G_8_SW\n')
        (catalogue / 'manifest.json').write_text(json.dumps({
            'complete': True, 'states': {'1': 'State'}, 'finished_at': 'earlier',
            'districts': [{'file': 'sheets.txt', 'sheet_count': 1, 'state': 'State', 'district': 'District'}],
        }))
        def download_index(path):
            path.write_bytes(index_zip())
            return {'source': 'test index'}
        def download_inventory(path):
            path.write_text('name,size,url\n52G_8_SW.pdf,1,https://example.test/file.pdf\n')
            return {'source': 'test inventory'}
        with patch.object(refresh, 'download_index', side_effect=download_index), \
                patch.object(refresh, 'download_inventory', side_effect=download_inventory), \
                patch.object(refresh.catalogue, 'scrape') as scrape:
            result = refresh.refresh(self.root, reuse_catalogue=True)
        scrape.assert_not_called()
        self.assertEqual((self.root / 'sheet_nos_to_lookup.txt').read_text(), '52G_7_SW\n')
        self.assertTrue(result['catalogue_reused'])
        self.assertEqual(result['catalogue_finished_at'], 'earlier')

    def test_failed_fresh_catalogue_preserves_previous_retry_list(self):
        path = self.root / 'sheet_nos_to_lookup.txt'
        path.write_text('previous list\n')
        with patch.object(refresh, 'download_index', return_value={}), patch.object(refresh, 'download_inventory', return_value={}), \
                patch.object(refresh.catalogue, 'scrape', side_effect=RuntimeError('incomplete')) as scrape, \
                patch.object(refresh.lists, 'build') as build:
            with self.assertRaises(RuntimeError):
                refresh.refresh(self.root, workers=3)
        scrape.assert_called_once_with(self.root / 'list_current', workers=3, refresh=True)
        build.assert_not_called()
        self.assertEqual(path.read_text(), 'previous list\n')


if __name__ == '__main__':
    unittest.main()
