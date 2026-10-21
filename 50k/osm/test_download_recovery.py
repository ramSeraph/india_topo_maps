import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import requests

SCRIPT = Path(__file__).with_name('scrape_unavailable.py')
spec = importlib.util.spec_from_file_location('scraper', SCRIPT)
scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraper)


def response(body, content_type='text/html; charset=utf-8'):
    result = requests.Response()
    result.status_code = 200
    result._content = body.encode()
    result.headers['Content-Type'] = content_type
    return result


class RecoveryTests(unittest.TestCase):
    def test_failed_post_restarts_with_fresh_form_and_captcha(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / '52G_7.pdf'
            form = lambda token: response(f'<form id="masterform"><input type="hidden" name="__VIEWSTATE" value="{token}"></form>')
            client = Mock()
            client.get.side_effect = [form('old'), form('new')]
            client.post.side_effect = [form('captcha-old'), requests.exceptions.ProxyError(),
                                       form('captcha-new'), response('%PDF-test', 'application/pdf')]
            with patch.object(scraper, 'session', client), patch.object(scraper, 'get_file_name', return_value=str(output)), \
                    patch.object(scraper, 'get_captcha_from_page', side_effect=['ABCDEF', 'GHIJKL']) as captcha, \
                    patch.object(scraper.time, 'sleep') as sleep:
                scraper.download_tile_wrap({'id': '52G_7'})
            self.assertEqual(output.read_bytes(), b'%PDF-test')
            self.assertEqual(client.get.call_count, 2)
            self.assertEqual(captcha.call_count, 2)
            self.assertEqual([c.kwargs['data']['__VIEWSTATE'] for c in client.post.call_args_list],
                             ['old', 'captcha-old', 'new', 'captcha-new'])
            self.assertEqual(client.post.call_args_list[-1].kwargs['data']['ctl00$ContentPlaceHolder1$txtCaptchaMtr'], 'GHIJKL')
            for c in client.get.call_args_list + client.post.call_args_list:
                self.assertEqual(c.kwargs['timeout'], scraper.REQUEST_TIMEOUT)
            sleep.assert_called_once_with(5)

    def test_persistent_proxy_failure_stops_with_original_error(self):
        error = requests.exceptions.ProxyError('unreachable')
        with patch.object(scraper, 'download_tile', side_effect=error) as download, patch.object(scraper.time, 'sleep') as sleep:
            with self.assertRaises(requests.exceptions.ProxyError) as caught:
                scraper.download_tile_wrap({'id': '52G_7'})
        self.assertIs(caught.exception, error)
        self.assertEqual(download.call_count, 5)
        self.assertEqual(sleep.call_args_list, [call(5), call(10), call(20), call(40)])

    def test_network_and_captcha_budgets_are_separate(self):
        failures = [Exception('Captcha Failed'), requests.Timeout(),
                    requests.exceptions.ChunkedEncodingError(), None]
        with patch.object(scraper, 'MAX_CAPTCHA_ATTEMPTS', 2), \
                patch.object(scraper, 'download_tile', side_effect=failures) as download, patch.object(scraper.time, 'sleep'):
            scraper.download_tile_wrap({'id': '52G_7'})
        self.assertEqual(download.call_count, 4)

    def test_only_transient_http_errors_are_retried(self):
        for status in (403, 404, 429, 502, 503, 504):
            with self.subTest(status=status):
                resp = response('error')
                resp.status_code = status
                error = requests.HTTPError(response=resp)
                with patch.object(scraper, 'download_tile', side_effect=[error, None]) as download, patch.object(scraper.time, 'sleep'):
                    if status in scraper.RETRYABLE_HTTP_STATUS:
                        scraper.download_tile_wrap({'id': '52G_7'})
                        self.assertEqual(download.call_count, 2)
                    else:
                        with self.assertRaises(requests.HTTPError):
                            scraper.download_tile_wrap({'id': '52G_7'})
                        self.assertEqual(download.call_count, 1)

    def test_permanent_errors_do_not_retry(self):
        for error in (Exception('Limit Crossed'), ValueError('bad form'), requests.exceptions.SSLError()):
            with self.subTest(error=type(error).__name__):
                with patch.object(scraper, 'download_tile', side_effect=error) as download, patch.object(scraper.time, 'sleep') as sleep:
                    with self.assertRaises(type(error)):
                        scraper.download_tile_wrap({'id': '52G_7'})
                self.assertEqual(download.call_count, 1)
                sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
