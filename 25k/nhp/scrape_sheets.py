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

import logging
import json
import time
import zipfile
import io
import argparse
from datetime import datetime, timezone
import os

import requests

from pathlib import Path

from bs4 import BeautifulSoup
from nhp_portal import get_error_alert, get_product_selection, get_submit_control, normalize_sheet_no, require_pdf_picker

from soi_common.captcha_helper import (
     check_captcha_models,
     CAPTCHA_MANUAL,
     captcha_model_dir
)
from soi_common.login import login_wrap, get_form_data, get_secrets
from soi_common.common import (
    base_url,
    setup_logging,
    session,
)


DELAY = 1
REQUEST_TIMEOUT = (20, 120)
logger = logging.getLogger(__name__)

data_dir = 'data/'
raw_data_dir = data_dir + 'raw/'

class DelayedRetriableException(Exception):
    pass
class KnownException(Exception):
    pass
class PortalError(Exception):
    pass

def check_for_error(resp, err_file=None):
    if 'text/html' in resp.headers.get('Content-Type', '').lower() or resp.content.lstrip().startswith(b'<'):
        message = get_error_alert(BeautifulSoup(resp.text, 'html.parser'))
        if message:
            if err_file is not None:
                err_file.write_text(resp.text)
            raise PortalError(message)
    resps = list(resp.history) + [resp]
    for r in resps:
        if '/Errorpage.aspx' in str(r.url):
            soup = BeautifulSoup(resp.text, 'html.parser')
            main_div = soup.find('div', { 'id': 'divMain'})
            err_div = main_div.find('div', { 'class': 'errorHeading'})
            err_text = err_div.text
            err_strings = [ 'Ooops! Something went wrong.',
                            'We apologize for the inconvenience. Please try again later.']
            for e in err_strings:
                if e in err_text:
                    if err_file is not None:
                        err_file.write_text(resp.text)
                    logging.error('Some retriable error happened, error text: %s', err_text)
                    raise KnownException(err_text)
            raise Exception('Some Error Happened')

def scrape(phone_num, password, otp_from_pb, typ, sheet_list):

    login_wrap(phone_num, password, otp_from_pb)

    logging.info('Product Show page scraping')
    dp_page = base_url + 'Digital_Product_Show.aspx'
    response = session.get(dp_page, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    form_data = get_form_data(soup)
    post_data = {
        'ctl00$ContentPlaceHolder1$rblDigitalProduct': '12',
        'ctl00$ContentPlaceHolder1$rblFormats': 'All',
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$rblDigitalProduct$3',
    }
    form_data.update(post_data)
    headers = {
        "origin": base_url[:-1],
        "referer": dp_page,
        "content-type": "application/x-www-form-urlencoded",
    }

    logging.info('Navigating to SOI project page listing')
    resp = session.post(dp_page, headers=headers, data=form_data, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        raise RuntimeError('Unable to open the digital product listing')
    check_for_error(resp)

    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update(get_product_selection(soup, typ))
    form_data.update({
        'ctl00$ContentPlaceHolder1$rblFormats': 'All',
        'ctl00$ContentPlaceHolder1$rblDigitalProduct': '12',
    })

    logging.info(f'Navigating to the {typ} Product Specification page')
    resp = session.post(dp_page, headers=headers, data=form_data, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        raise Exception(f'Unable to navigate to the {typ} Product Specification page')
    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    require_pdf_picker(soup)
    form_data = get_form_data(soup)
    
    logging.info('Change to pdf listing')
    form_data.update({
        'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
        'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
        'ctl00$ContentPlaceHolder1$ddlstate': '0',
        'ctl00$ContentPlaceHolder1$ddldist': '0',
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlFormateTyoe',
    })
    sheet_picker_url = resp.url
    resp = session.post(sheet_picker_url, headers=headers, data=form_data, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        raise Exception('Unable to post to change to pdf listing')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    sheet_picker_form_data = get_form_data(soup)

    total_count = len(sheet_list)
    logging.info(f'Total sheets to download: {total_count}')
    done_count = 0
    for sheet_no in sheet_list:

        logging.info(f'Downloading sheet {done_count + 1}/{total_count}: {sheet_no}')
        out_file = Path(raw_data_dir) / f'{sheet_no}.pdf'
        out_html_file = out_file.with_suffix('.html')
        valid_pdf = False
        if out_file.exists():
            with out_file.open('rb') as stream:
                valid_pdf = stream.read(5) == b'%PDF-'
        if valid_pdf:
            logging.info(f'Sheet {sheet_no} already done, skipping')
            done_count += 1
            continue

        form_data = sheet_picker_form_data.copy()
        form_data.update({
            'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
            'ctl00$ContentPlaceHolder1$txtSheetNumber': sheet_no.replace('_', ''),
            'ctl00$ContentPlaceHolder1$ddlstate': '0',
            'ctl00$ContentPlaceHolder1$ddldist': '0',
            '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$lbtnAddToCart'
        })
        time.sleep(DELAY)
        logging.info(f'Adding sheet {sheet_no} to cart')
        resp = session.post(sheet_picker_url, headers=headers, data=form_data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise Exception(f'Unable to post to add sheet {sheet_no} to cart')

        check_for_error(resp)
        soup = BeautifulSoup(resp.text, 'html.parser')
        form_data = get_form_data(soup)
        form_data.update({
            'ctl00$ContentPlaceHolder1$btnViewCart': 'View Cart'
        })

        time.sleep(DELAY)
        logging.info(f'Viewing cart for sheet {sheet_no}')
        resp = session.post(sheet_picker_url, headers=headers, data=form_data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise Exception(f'Unable to post to view cart for sheet {sheet_no}')

        new_headers = headers.copy()
        new_headers['referer'] = resp.url
        form_data = get_form_data(BeautifulSoup(resp.text, 'html.parser'))
        form_data.update({
            'ctl00$ContentPlaceHolder1$btnplaceorder': 'Place Order',
            'ctl00$ContentPlaceHolder1$HiddenField1': ''
        })

        time.sleep(DELAY)
        logging.info(f'Placing order for sheet {sheet_no}')
        resp = session.post(resp.url, headers=new_headers, data=form_data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise Exception(f'Unable to post to place order for sheet {sheet_no}')

        try:
            check_for_error(resp)
        except KnownException:
            logging.warning(f'Failed to place order for sheet {sheet_no}; will retry')
            raise DelayedRetriableException('Unable to place order, trying again')

        soup = BeautifulSoup(resp.text, 'html.parser')
        form_data = get_form_data(soup)
        form_data.update({
            'ctl00$ContentPlaceHolder1$btnSubmitPrivateIndenter': 'I Agree',
            'ctl00$ContentPlaceHolder1$HiddenField1': ''
        })
        new_headers['referer'] = resp.url
        time.sleep(DELAY)
        logging.info(f'Agree to terms and conditions for sheet {sheet_no}')
        resp = session.post(resp.url, headers=new_headers, data=form_data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise Exception(f'Unable to post to agree to T&C for sheet {sheet_no}')

        check_for_error(resp)
        soup = BeautifulSoup(resp.text, 'html.parser')
        form_data = get_form_data(soup)
        form_data.update(get_submit_control(soup, 'btnProceedDownload', sheet_no))
        form_data.update({
            'ctl00$ContentPlaceHolder1$HiddenField1': ''
        })
        new_headers['referer'] = resp.url
        logging.info(f'Proceeding to download for sheet {sheet_no}')

        time.sleep(DELAY)
        resp = session.post(resp.url, headers=new_headers, data=form_data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise Exception(f'Unable to post to proceed to download for sheet {sheet_no}')

        check_for_error(resp)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # SOI may offer Download immediately, or require the preparation steps.
        for control in ('btnRequest', 'btnGenerateDownloadLink'):
            if get_submit_control(soup, 'btnDownloadMap', sheet_no, required=False):
                break
            action = get_submit_control(soup, control, sheet_no, required=False)
            if action is None:
                continue
            form_data = get_form_data(soup)
            form_data.update(action)
            new_headers['referer'] = resp.url
            time.sleep(DELAY)
            logging.info(f'Preparing download for sheet {sheet_no}: {control}')
            resp = session.post(resp.url, headers=new_headers, data=form_data, timeout=REQUEST_TIMEOUT)
            if not resp.ok:
                raise Exception(f'Unable to prepare download for sheet {sheet_no}')
            check_for_error(resp)
            soup = BeautifulSoup(resp.text, 'html.parser')

        form_data = get_form_data(soup)
        form_data.update(get_submit_control(soup, 'btnDownloadMap', sheet_no))
        new_headers['referer'] = resp.url
        time.sleep(DELAY)
        logging.info(f'Downloading sheet {sheet_no}')
        resp = session.post(resp.url, headers=new_headers, data=form_data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise Exception(f'Unable to post to download sheet {sheet_no}')
        check_for_error(resp, err_file=out_file.with_suffix('.html'))
        zip_file_contents = resp.content
        # decode the zip file and locate the pdf inside it
        if not zipfile.is_zipfile(io.BytesIO(zip_file_contents)):
            out_html_file.write_text(resp.text)
            logger.error(f'Zip file not received for sheet {sheet_no}, check the html file')
            done_count += 1
            raise DelayedRetriableException('Unable to get zip file, trying again')
        # use buffered io to treat the bytes as a file and use the zip file module to pull out the pdf
        zip_buffer = io.BytesIO(zip_file_contents)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            namelist = zf.namelist()
            pdf_files = [ x for x in namelist if x.lower().endswith('.pdf') ]
            if len(pdf_files) == 0:
                out_file.with_suffix('.html').write_text(resp.text)
                raise Exception(f'No pdf file found in the zip for sheet {sheet_no}, check the html file')
            if len(pdf_files) > 1:
                out_file.with_suffix('.html').write_text(resp.text)
                raise Exception(f'Multiple pdf files found in the zip for sheet {sheet_no}, check the html file')
            pdf_file_name = pdf_files[0]
            content = zf.read(pdf_file_name)
            if not content.startswith(b'%PDF-'):
                raise RuntimeError(f'Invalid PDF in download for {sheet_no}')
            temporary = out_file.with_suffix('.pdf.part')
            temporary.write_bytes(content)
            temporary.replace(out_file)
        logging.info(f'Sheet {sheet_no} written to {out_file}')
        done_count += 1


    return True



def scrape_wrap(otp_from_pb, typ, sheet_list):
    secrets_map = get_secrets()
    if not secrets_map:
        raise RuntimeError('No enabled accounts in data/users.json')
    phone_num, password = next(iter(secrets_map.items()))
    for attempt in range(3):
        try:
            return scrape(phone_num, password, otp_from_pb, typ, sheet_list)
        except (KnownException, DelayedRetriableException, requests.ConnectionError,
                requests.Timeout, requests.exceptions.ChunkedEncodingError) as ke:
            if attempt == 2:
                raise
            logger.warning('Temporary SOI failure (%s); retrying in 60s', type(ke).__name__)
            time.sleep(60)
            if isinstance(ke, requests.RequestException):
                continue
            saved_cookie_file = Path(f'data/cookies/saved_cookies.{phone_num}.pkl')
            saved_cookie_file.unlink(missing_ok=True)
            # Login, CAPTCHA, and this scraper share the same Session object.
            # Rebinding common.session leaves the imported references stale.
            session.cookies.clear()


def download_batch(sheet_list, report_path, keep_going=False):
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    Path(raw_data_dir).mkdir(parents=True, exist_ok=True)
    records = []
    for sheet_no in dict.fromkeys(normalize_sheet_no(s) for s in sheet_list):
        output = Path(raw_data_dir) / f'{sheet_no}.pdf'
        record = {'sheet_no': sheet_no, 'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'interrupted'}
        try:
            existed = output.exists() and output.read_bytes().startswith(b'%PDF-')
            if not existed:
                scrape_wrap(True, 'NHP', [sheet_no])
            if not output.exists() or not output.read_bytes().startswith(b'%PDF-'):
                raise RuntimeError('SOI did not return a valid PDF')
            record.update({'status': 'already_local' if existed else 'downloaded', 'bytes': output.stat().st_size})
        except Exception as exc:
            record.update({'status': 'failed', 'error_type': type(exc).__name__,
                           'error': type(exc).__name__ if isinstance(exc, requests.RequestException) else str(exc)})
            logger.warning('Sheet %s failed: %s', sheet_no, record['error'])
            if not keep_going:
                raise
        finally:
            records.append(record)
            temporary = report_path.with_name(report_path.name + '.tmp')
            temporary.write_text(json.dumps(records, indent=2) + '\n')
            temporary.replace(report_path)
    return records


def main():
    parser = argparse.ArgumentParser(description='Download NHP sheets and record each result')
    parser.add_argument('sheets', nargs='?', type=Path, default=Path('data/sheet_nos_to_lookup.txt'))
    parser.add_argument('--keep-going', action='store_true', help='Try remaining sheets after a download failure')
    parser.add_argument('--report', type=Path, default=Path('data/download_attempts.json'))
    parser.add_argument('--pushbullet-token-file', type=Path, help='Read PB_TOKEN from a local file')
    parser.add_argument('--models-dir', default=captcha_model_dir)
    args = parser.parse_args()
    setup_logging(logging.INFO)
    if args.pushbullet_token_file:
        os.environ['PB_TOKEN'] = args.pushbullet_token_file.read_text().strip()
    if not CAPTCHA_MANUAL:
        from soi_common import captcha_helper
        captcha_helper.captcha_model_dir = args.models_dir
        check_captcha_models(args.models_dir)
    sheets = [s.strip() for s in args.sheets.read_text().splitlines() if s.strip()]
    records = download_batch(sheets, args.report, args.keep_going)
    failed = sum(r['status'] == 'failed' for r in records)
    logger.info('Finished %s sheets: %s downloaded, %s already local, %s failed; report: %s',
                len(records), sum(r['status'] == 'downloaded' for r in records),
                sum(r['status'] == 'already_local' for r in records), failed, args.report)
    return int(failed > 0)


if __name__ == '__main__':
    raise SystemExit(main())

