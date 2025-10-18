# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "soi-common",
# ]
#
# [tool.uv.sources]
# soi-common = { git = "https://github.com/ramseraph/soi_common" }
# ///

import json
import logging
import shutil

from pprint import pformat, pprint
from pathlib import Path

from bs4 import BeautifulSoup

from soi_common.captcha_helper import (
     get_captcha_from_page,
     check_captcha_models,
     CAPTCHA_MANUAL,
     captcha_model_dir
)
from soi_common.login import login_wrap, get_form_data, MAX_CAPTCHA_ATTEMPTS, get_secrets
from soi_common.common import (
    base_url,
    setup_logging,
    ensure_dir,
    session,
    data_dir,
    raw_data_dir
)

logger = logging.getLogger(__name__)



tried_users_file = data_dir + 'tried_users.txt'
def get_tried_users():
    if not Path(tried_users_file).exists():
        return []
    with open(tried_users_file, 'r') as f:
        tried_users = f.read().split('\n')
    return [ x.strip() for x in tried_users ]


def update_tried_users(tried_users):
    tried_users_file_new = tried_users_file + '.new'
    with open(tried_users_file_new, 'w') as f:
        f.write('\n'.join(tried_users))
    shutil.move(tried_users_file_new, tried_users_file)
    

def get_tile_infos(map_index_file):
    with open(map_index_file, 'r') as f:
        map_data = json.load(f)
    features = map_data['features']
    return [ x['properties'] for x in features ]


def get_download_tile_form_data(soup, sheet_no, first_pass=True):
    captcha = ''
    form_data = {}
    form_data['ctl00$ContentPlaceHolder1$ddlstate'] = '0'
    form_data['ctl00$ContentPlaceHolder1$ddldist'] = '0'
    form_data['ctl00$ContentPlaceHolder1$txtSheetNumber'] = sheet_no.replace('_', '/')
    form_data['__EVENTTARGET'] = 'ctl00$ContentPlaceHolder1$lbtnDownloadMap'

    if not first_pass:
        captcha = get_captcha_from_page(soup)
        form_data['ctl00$ContentPlaceHolder1$CheckBox1'] = 'on'
        form_data['ctl00$ContentPlaceHolder1$Button_ok'] = 'OK'
        form_data['__EVENTTARGET'] = ''

    form_data['ctl00$ContentPlaceHolder1$txtCaptchaMtr'] = captcha
    return form_data

def sort_key(x):
    parts = x.split('_')
    return (parts[0], int(parts[1]))

combined_file_map = None
def get_file_name(sheet_no):
    global combined_file_map
    if combined_file_map is None:
        combined_file_map = {}
        combined_files_file = data_dir + 'combined_files_50k.json'
        if Path(combined_files_file).exists():
            with open(combined_files_file, 'r') as f:
                data = json.load(f)
            for entry in data:
                entry = sorted(entry, key=sort_key)
                combined = '-'.join(entry)
                for sheet in entry:
                    combined_file_map[sheet] = combined


    if sheet_no in combined_file_map:
        sheet_no = combined_file_map[sheet_no]

    return raw_data_dir + f"{sheet_no}.pdf"

def download_tile(sheet_no):
    file_name = get_file_name(sheet_no)
    
    out_file = Path(file_name)
    out_file_unavailable = Path(str(out_file) + '.unavailable')
    file_to_write = out_file
    if out_file.exists() or out_file_unavailable.exists():
        logger.info(f'{out_file} exists.. skipping')
        return

    
    url = base_url + 'FreeMapSpecification.aspx'
    resp = session.get(url)
    if not resp.ok:
        raise Exception('unable to get FreeMapSpec page')
    soup = BeautifulSoup(resp.text, 'html.parser')

    form_data = get_form_data(soup)
    form_data.update(get_download_tile_form_data(soup, sheet_no, first_pass=True))
    logger.debug(f'spec page form data first pass:\n{pformat(form_data)}')
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': base_url + 'FreeMapSpecification.aspx',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        'Origin': base_url[:-1],
        'Host': base_url[8:-1],
    }

    url = base_url + 'FreeMapSpecification.aspx'
    resp = session.post(url, data=form_data, headers=headers)
    logger.debug(f'status_code = {resp.status_code} headers:\n{pformat(dict(resp.headers))}')
    if not resp.ok:
        raise Exception(f'unable to lookup {sheet_no} in FreeMapSpec page')

    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update(get_download_tile_form_data(soup, sheet_no, first_pass=False))
    logger.debug(f'spec page form data second pass:\n{pformat(form_data)}')
    resp = session.post(url, data=form_data, headers=headers)
    logger.debug(f'status_code = {resp.status_code} headers:\n{pformat(dict(resp.headers))}')
    if not resp.ok:
        raise Exception('unable to download {sheet_no=}')

    if resp.headers['Content-Type'] != 'text/html; charset=utf-8':
        content = resp.content
    else:
        soup = BeautifulSoup(resp.text, 'html.parser')

        captcha_failed = soup.find('span', { 'id': 'ContentPlaceHolder1_lblWrongCaptcha'})
        CAPTCHA_FAILED_MSG = 'Please enter valid captcha code'
        if captcha_failed is not None and captcha_failed.text == CAPTCHA_FAILED_MSG:
            raise Exception('Captcha Failed')

        limit_crossed = soup.find('span', { 'id': 'ContentPlaceHolder1_msgbox_lblMsg'})
        LIMIT_CROSSED_MSG = 'You have crossed your download limit for today'
        if limit_crossed is not None and limit_crossed.text == LIMIT_CROSSED_MSG:
            raise Exception('Limit Crossed')

        error_heading = soup.find('div', {'class': 'errorHeading'})
        if error_heading is not None:
            raise Exception(f'Unexpected Error: {error_heading.text}')

        not_found = soup.find('span', {'id':'ContentPlaceHolder1_lblSheetNotExist'})
        NOT_FOUND_MSG = 'Sheet Number is not exist... Please enter valid Sheet Number.'
        if not_found is not None and not_found.text.strip() == NOT_FOUND_MSG:
            logger.warning('sheet not found, writing unavailable file')
            file_to_write = out_file_unavailable
            content = b''
        else:
            with open('failed.html', 'w') as f:
                f.write(resp.text)
            logger.error(f'status_code = {resp.status_code} headers:\n{pformat(dict(resp.headers))}')
            logger.error(resp.text)
            raise Exception(f'Expected pdf got html for {sheet_no}')


    #TODO check if returned content is pdf or html?
    ensure_dir(file_to_write)
    logger.info(f'writing file {file_to_write}')
    with open(file_to_write, 'wb') as f:
        f.write(content)
    return out_file



def download_tile_wrap(tile_info):
    count = 0
    success = False
    sheet_no = tile_info['id']
    logger.info(f'downloading {sheet_no=}')
    while count < MAX_CAPTCHA_ATTEMPTS:
        try:
            download_tile(sheet_no)
            success = True
            break
        except Exception as ex:
            if str(ex) != 'Captcha Failed':
                raise ex
            count += 1
            logger.warning('captcha failed..')

    if not success:
        raise Exception('download tile map because of captcha errors')


def get_done_set():
    filename = data_dir + 'files_done.txt'
    if not Path(filename).exists():
        return []

    with open(filename, 'r') as f:
        files_done = f.read().split('\n')
        files_done = [ x.replace('.pdf', '') for x in files_done ]

    sheet_nos = set()
    for x in files_done:
        if x.strip() == '':
            continue
        parts = x.strip().split('-')
        for part in parts:
            sheet_nos.add(part.strip())

    return sheet_nos

def is_sheet_done(sheet_no, done):
    if sheet_no in done:
        return True

    base_file = get_file_name(sheet_no) + '.pdf'
    base_file_unavailable = base_file + '.unavailable'

    out_file = Path(base_file)
    out_file_unavailable = Path(base_file_unavailable)

    if out_file.exists() or out_file_unavailable.exists():
        return True

    return False

def scrape(phone_num, password, otp_from_pb):
    login_wrap(phone_num, password, otp_from_pb)
    map_index_file = Path(data_dir).joinpath('index_50k.geojson')
    if not map_index_file.exists():
        raise Exception(f'{map_index_file} is missing')

    tile_infos = get_tile_infos(map_index_file)
    logger.info(f'got {len(tile_infos)} tiles')

    done_set = get_done_set()
    tile_infos_to_download = []
    for tile_info in tile_infos:
        sheet_no = tile_info['id']
        if is_sheet_done(sheet_no, done_set):
            continue
        tile_infos_to_download.append(tile_info)

    done = 0
    for tile_info in tile_infos_to_download:
        download_tile_wrap(tile_info)
        done += 1
        logger.info(f'Done: {done}/{len(tile_infos_to_download)}')


def scrape_wrap(otp_from_pb):
    global session
    secrets_map = get_secrets()
    p_idx = 0
    tried_users = get_tried_users()
    secrets_map = {k:v for k,v in secrets_map.items() if k not in tried_users}
    total_count = len(secrets_map)
    for phone_num, password in secrets_map.items():
        p_idx += 1
        try:
            logger.info(f'scraping with phone number: {p_idx}/{total_count}')
            scrape(phone_num, password, otp_from_pb)
            logger.warning('No more Sheets')
            if Path(tried_users_file).exists():
                Path(tried_users_file).unlink()
            return
        except Exception as ex:
            if str(ex) != 'Limit Crossed':
                raise
            logger.warning('Limit crossed for this user.. changing users')
            tried_users.append(phone_num)
            update_tried_users(tried_users)
            #session = requests.session()
    logger.warning('No more users')
    if Path(tried_users_file).exists():
        Path(tried_users_file).unlink()

   


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--max-captcha-retries', help='max number of times a captcha is retried', type=int, default=MAX_CAPTCHA_ATTEMPTS)
    parser.add_argument('-p', '--otp-from-pushbullet', help='get login otp from pushbullet(provide token using the PB_TOKEN env variable)', action='store_true')
    args = parser.parse_args()
    MAX_CAPTCHA_ATTEMPTS = args.max_captcha_retries

    setup_logging(logging.INFO)

    if not CAPTCHA_MANUAL:
        check_captcha_models(captcha_model_dir)

    scrape_wrap(args.otp_from_pushbullet)

