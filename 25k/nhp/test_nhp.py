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

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from bs4 import BeautifulSoup
import requests

import build_download_list as lists
import nhp_portal as portal
import scrape_available as catalogue
import scrape_sheets as downloader


def soup(text):
    return BeautifulSoup(text, 'html.parser')


def sheet_page(sheet, pager=''):
    return soup(f'<table id="ContentPlaceHolder1_GridView1"><tr><td>'
                f'<span id="x_lblsheetno_0">{sheet}</span></td></tr>{pager}</table>')


class PortalTests(unittest.TestCase):
    def test_server_download_alert_is_reported_without_relogin(self):
        page = soup("<script>// alert('Viewing source is disabled');\nalert('Error during Downloading File please contact Survey of India.')</script>")
        self.assertEqual(portal.get_error_alert(page), 'Error during Downloading File please contact Survey of India.')
        response = requests.Response()
        response._content = str(page).encode()
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.url = 'https://example.test/download'
        with self.assertRaisesRegex(downloader.PortalError, 'Error during Downloading File'):
            downloader.check_for_error(response)

    def test_direct_download_retries_old_error_marker(self):
        def response(body):
            result = requests.Response()
            result.status_code = 200
            result.url = 'https://example.test/product.aspx'
            result._content = ('<form id="masterform"><input type="hidden" name="__VIEWSTATE" value="state">'
                               + body + '</form>').encode()
            return result

        product = '<div class="cardsa"><span id="x_Label3_1">NHP(3-5m) Maps</span><input type="submit" name="product$Button2" value="Click to Buy"></div>'
        picker = '<select id="ContentPlaceHolder1_ddlFormateTyoe"><option value="pdf">PDF</option></select>'
        button_row = lambda name: f'<table><tr><td>52G7SW</td><td><input type="submit" name="newGrid$ctl02${name}" value="Go"></td></tr></table>'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('52G7SW.pdf', b'%PDF-test')
        download = response('')
        # SOI may serve a valid ZIP with a generic download content type.
        download.headers['content-type'] = 'application/octet-stream'
        download._content = buffer.getvalue()
        client = Mock()
        client.get.return_value = response('')
        client.post.side_effect = [response(product), response(picker), response(''), response(''),
                                   response(''), response(''), response(button_row('btnProceedDownload')),
                                   response(button_row('btnDownloadMap')), download]
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            (raw / '52G_7_SW.html').write_text('old failed attempt')
            with patch.object(downloader, 'raw_data_dir', directory), patch.object(downloader, 'login_wrap'), \
                    patch.object(downloader, 'session', client), patch.object(downloader.time, 'sleep'):
                downloader.scrape('user', 'password', True, 'NHP', ['52G_7_SW'])
            self.assertEqual((raw / '52G_7_SW.pdf').read_bytes(), b'%PDF-test')
        self.assertEqual(client.post.call_count, 9)
        self.assertIn('newGrid$ctl02$btnDownloadMap', client.post.call_args.kwargs['data'])
        self.assertFalse(any('btnRequest' in key or 'btnGenerateDownloadLink' in key
                             for c in client.post.call_args_list for key in c.kwargs['data']))

    def test_normalizes_sheet_identifiers(self):
        for value in ('52g07sw ', '52G/7/SW', '52G_7_SW.pdf', '52G-7-SW'):
            self.assertEqual(portal.normalize_sheet_no(value), '52G_7_SW')
        for value in ('52G17SW', '52G0SW', 'H43D9SE', ''):
            with self.assertRaises(ValueError):
                portal.normalize_sheet_no(value)

    def test_selects_named_product_instead_of_fixed_button_number(self):
        page = soup('<div class="cardsa"><span id="x_Label3_0">Other Maps</span>'
                    '<input type="submit" name="other$Button4" value="Click to Buy"></div>'
                    '<div class="cardsa"><span id="x_Label3_1">NHP(3-5m) Maps</span>'
                    '<input type="submit" name="nhp$Button2" value="Click to Buy"></div>')
        self.assertEqual(portal.get_product_selection(page), {'nhp$Button2': 'Click to Buy'})
        with self.assertRaises(RuntimeError):
            portal.require_pdf_picker(page)

    def test_selects_enabled_download_for_requested_sheet(self):
        page = soup('<table><tr><td>52G7SE</td><td><input type="submit" name="a$btnDownloadMap"></td></tr>'
                    '<tr><td>52G7SW</td><td><input type="submit" name="b$btnDownloadMap" disabled></td></tr>'
                    '<tr><td>52G7SW</td><td><input type="submit" name="c$btnDownloadMap" value="Download"></td></tr></table>')
        self.assertEqual(portal.get_submit_control(page, 'btnDownloadMap', '52G_7_SW'), {'c$btnDownloadMap': 'Download'})
        self.assertIsNone(portal.get_submit_control(page, 'btnRequest', required=False))
        with self.assertRaises(RuntimeError):
            portal.get_submit_control(page, 'btnDownloadMap', '52G_8_SW')

    def test_retry_keeps_shared_session_and_is_bounded(self):
        client = downloader.session
        with patch.object(downloader, 'get_secrets', return_value={'test-user': 'test-password'}), \
                patch.object(downloader, 'scrape', side_effect=downloader.KnownException('temporary')) as scrape, \
                patch.object(downloader.time, 'sleep'), patch.object(Path, 'unlink'), \
                patch.object(client.cookies, 'clear') as clear:
            with self.assertRaises(downloader.KnownException):
                downloader.scrape_wrap(True, 'NHP', ['52G_7_SW'])
        self.assertIs(downloader.session, client)
        self.assertEqual(scrape.call_count, 3)
        self.assertEqual(clear.call_count, 2)

    def test_batch_continues_and_records_failure_without_redownloading_local_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '52G_3_SW.pdf').write_bytes(b'%PDF-local')
            def attempt(otp, product, sheets):
                if sheets == ['52G_1_SW']:
                    raise RuntimeError('Sheet not offered')
                (root / f'{sheets[0]}.pdf').write_bytes(b'%PDF-downloaded')
            with patch.object(downloader, 'raw_data_dir', directory), \
                    patch.object(downloader, 'scrape_wrap', side_effect=attempt) as scrape:
                records = downloader.download_batch(['52G1SW', '52G2SW', '52G3SW'], root / 'report.json', keep_going=True)
            self.assertEqual([r['status'] for r in records], ['failed', 'downloaded', 'already_local'])
            self.assertEqual(scrape.call_count, 2)
            self.assertEqual(json.loads((root / 'report.json').read_text()), records)


class CatalogueTests(unittest.TestCase):
    def test_pagination_rejects_stale_page_and_follows_next(self):
        page = sheet_page('52G7SW', '<tr class="grid-pager"><td><span>1</span>'
                          '<a href="javascript:__doPostBack(\'grid\',\'Page$2\')">2</a></td></tr>')
        self.assertEqual(catalogue.parse_sheet_page(page, 1), (['52G_7_SW'], 2))
        with self.assertRaises(RuntimeError):
            catalogue.parse_sheet_page(page, 2)

    def test_every_district_starts_with_original_viewstate(self):
        initial = soup('<input id="ContentPlaceHolder1_hdnproductsCode" value="NHP">')
        response = Mock()
        response.json.return_value = {'d': [
            {'DistrictID': '1', 'DistrictName': 'First'},
            {'DistrictID': '2', 'DistrictName': 'Second'},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(catalogue, 'new_client'), \
                    patch.object(catalogue, 'open_listing', return_value=('https://example.test/product', initial)), \
                    patch.object(catalogue, 'request', return_value=response), \
                    patch.object(catalogue, 'post_page', side_effect=[('url', sheet_page('52G7SW')), ('url', sheet_page('52G8SW'))]) as post:
                records = catalogue.scrape_state('1', 'State', Path(directory))
            self.assertEqual(len(records), 2)
            self.assertTrue(all(c.args[2] is initial for c in post.call_args_list))
            self.assertEqual((Path(directory) / records[0]['file']).read_text(), '52G_7_SW\n')
            self.assertEqual((Path(directory) / records[1]['file']).read_text(), '52G_8_SW\n')


class DownloadListTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_nested_index_uses_topo_identifier(self):
        kml = '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>H43D9SE</name><description><![CDATA[<table><tr><td>TOPO_SHEET</td><td>44M9SE </td></tr></table>]]></description></Placemark></Document></kml>'
        kmz = io.BytesIO()
        with zipfile.ZipFile(kmz, 'w') as archive:
            archive.writestr('doc.kml', kml)
        path = self.root / 'index.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('index.kmz', kmz.getvalue())
        self.assertEqual(lists.read_index(path), ({'44M_9_SE'}, 1))

    def test_union_excludes_published_and_valid_local_files_only(self):
        index = self.root / 'index.kml'
        index.write_text('<kml><Document>' + ''.join(f'<Placemark><name>52G{i}SW</name></Placemark>' for i in (1, 2, 3)) + '</Document></kml>')
        catalogue_dir = self.root / 'catalogue'
        catalogue_dir.mkdir()
        (catalogue_dir / 'sheets.txt').write_text('52G_2_SW\n52G_4_SW\n52G_5_SW\n')
        (catalogue_dir / 'stale.txt').write_text('52G_9_SW\n')
        (catalogue_dir / 'manifest.json').write_text(json.dumps({
            'complete': True, 'states': {'1': 'State'}, 'finished_at': 'today',
            'districts': [{'file': 'sheets.txt', 'sheet_count': 3, 'state': 'State', 'district': 'District'}],
        }))
        published = self.root / 'listing.csv'
        published.write_text('name,size,url\n52G_2_SW.pdf,123,https://example.test/extra4/file.pdf\n')
        raw = self.root / 'raw'
        raw.mkdir()
        (raw / '52G_3_SW.pdf').write_bytes(b'%PDF-valid')
        (raw / '52G_4_SW.pdf').write_bytes(b'<html>failed</html>')
        (raw / '52G_1_SW.pdf.unavailable').touch()
        (raw / '52G_5_SW.html').touch()
        output = self.root / 'output'
        summary = lists.build(index, catalogue_dir, published, raw, output)
        self.assertEqual((output / 'sheet_nos_to_lookup.txt').read_text().splitlines(), ['52G_1_SW', '52G_4_SW', '52G_5_SW'])
        self.assertEqual(summary['combined_candidates'], 5)
        self.assertEqual(summary['prior_failures_to_retry'], 2)
        with (output / 'sheet_availability.csv').open() as stream:
            rows = {r['sheet_no']: r for r in csv.DictReader(stream)}
        self.assertEqual(rows['52G_1_SW']['in_catalogue'], '0')
        self.assertEqual(rows['52G_4_SW']['in_index'], '0')
        self.assertEqual(rows['52G_2_SW']['published'], '1')

    def test_partial_catalogue_is_rejected(self):
        (self.root / 'manifest.json').write_text('{"complete": false}')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            lists.read_catalogue(self.root)

    def test_state_filtered_catalogue_is_rejected(self):
        (self.root / 'manifest.json').write_text('{"complete": true, "filtered": true}')
        with self.assertRaisesRegex(ValueError, 'selected states'):
            lists.read_catalogue(self.root)


if __name__ == '__main__':
    unittest.main()
