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
import shutil
import json
import time
import zipfile
import io

from pathlib import Path
from pprint import pprint

#import requests

from bs4 import BeautifulSoup

from soi_common.captcha_helper import (
     check_captcha_models,
     CAPTCHA_MANUAL,
     captcha_model_dir
)
from soi_common.login import login_wrap, get_form_data, get_secrets
from soi_common.common import (
    base_url,
    setup_logging,
    get_page_soup,
    session,
    reset_session,
)


DELAY = 1
logger = logging.getLogger(__name__)

data_dir = 'data/'
raw_data_dir = data_dir + 'raw/'
list_data_dir = data_dir + 'list/'

class DelayedRetriableException(Exception):
    pass
class KnownException(Exception):
    pass

def check_for_error(resp, err_file=None):
    global force_map_tried
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
                        d_file = err_file.parent
                        s_file = d_file.parent
                        s_name = s_file.name
                        d_name = d_file.name
                        if s_name not in force_map_tried:
                            force_map_tried[s_name] = {}
                        force_map_tried[s_name][d_name] = True

                        err_file.write_text(resp.text)
                    logging.error('Some retriable error happened, error text: %s', err_text)
                    raise KnownException(err_text)
            raise Exception('Some Error Happened')

def scrape():

    logging.info('Product Show page scraping')
    dp_page = base_url + 'Digital_Product_Show.aspx'
    soup = get_page_soup(dp_page)

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
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    }

    logging.info('Navigating to SOI project page listing')
    resp = session.post(dp_page, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception('Unable to post to get village shapefile listing')
    check_for_error(resp)

    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    key = 'ctl00$ContentPlaceHolder1$ListViewSingleProduct$ctrl1$Button4'

    form_data.update({
        key: 'Click to Buy',
        'ctl00$ContentPlaceHolder1$rblFormats': 'All',
        'ctl00$ContentPlaceHolder1$rblDigitalProduct': '12',
    })

    logging.info('Navigating to the Product Specification page')
    resp = session.post(dp_page, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception('Unable to navigate to the Product Specification page')
    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    
    form_data.update({
        'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
        'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
        'ctl00$ContentPlaceHolder1$ddlstate': '0',
        'ctl00$ContentPlaceHolder1$ddldist': '0',
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlFormateTyoe',
    })
    sheet_picker_url = resp.url
    logging.info('Change to pdf listing')
    resp = session.post(sheet_picker_url, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception('Unable to post to change to pdf listing')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
        'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
        'ctl00$ContentPlaceHolder1$ddlstate': '0',
        'ctl00$ContentPlaceHolder1$ddldist': '0',
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$lbtnSheetNumber',
    })
    logging.info('Change to state listing')
    resp = session.post(sheet_picker_url, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception('Unable to post to get state listing')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    state_form_data = get_form_data(soup)
    state_select = soup.find('select', { 'id': 'ContentPlaceHolder1_ddlstate' })
    states = state_select.find_all('option')
    state_map = { x['value']: x.text.strip() for x in states if x['value'] != '0' }
    for k, v in state_map.items():
        state_done_file = Path(list_data_dir) / v / 'done.txt'
        if state_done_file.exists():
            logging.info(f'State {v} already done, skipping')
            continue

        logging.info(f'State code {k}: {v}')
        form_data = state_form_data.copy()
        form_data.update({
            'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
            'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
            'ctl00$ContentPlaceHolder1$ddlstate': k,
            'ctl00$ContentPlaceHolder1$ddldist': '0',
            'ctl00$ContentPlaceHolder1$ddlProductsType': '',
            '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlstate'
        })
        time.sleep(DELAY)
        logging.info(f'Getting districts for state {v}')
        resp = session.post(sheet_picker_url, headers=headers, data=form_data)
        if not resp.ok:
            raise Exception(f'Unable to post to get districts for state {v}')

        check_for_error(resp)
        soup = BeautifulSoup(resp.text, 'html.parser')
        dist_form_data = get_form_data(soup)
        dist_select = soup.find('select', { 'id': 'ContentPlaceHolder1_ddldist' })
        dists = dist_select.find_all('option')
        dist_map = { x['value']: x.text.strip() for x in dists if x['value'] != '0' }
        for dk, dv in dist_map.items():
            if dv == 'All Districts':
                continue
            logging.info(f'District code {dk}: {dv}')
            dist_done_file = Path(list_data_dir) / v / dv / 'done.txt'
            if dist_done_file.exists():
                logging.info(f'District {dv}, state {v} already done, skipping')
                continue

            form_data = dist_form_data.copy()
            form_data.update({
                'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
                'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
                'ctl00$ContentPlaceHolder1$ddlstate': k,
                'ctl00$ContentPlaceHolder1$ddldist': dk,
                'ctl00$ContentPlaceHolder1$ddlProductsType': '',
                '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddldist'
            })
            time.sleep(DELAY)
            logging.info(f'Getting products for district {dv}, state {v}')
            resp = session.post(sheet_picker_url, headers=headers, data=form_data)
            if not resp.ok:
                raise Exception(f'Unable to post to get products for district {dv}, state {v}')

            check_for_error(resp)
            soup = BeautifulSoup(resp.text, 'html.parser')
            prod_form_data = get_form_data(soup)
            prod_form_data.update({
                'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
                'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
                'ctl00$ContentPlaceHolder1$ddlstate': k,
                'ctl00$ContentPlaceHolder1$ddldist': dk,
                'ctl00$ContentPlaceHolder1$ddlProductsType': 'pdf',
                '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlProductsType'
            })
            time.sleep(DELAY)
            logging.info(f'Getting sheet listing for district {dv}, state {v}')
            resp = session.post(sheet_picker_url, headers=headers, data=prod_form_data)
            if not resp.ok:
                raise Exception(f'Unable to post to get sheet listing for district {dv}, state {v}')
            #with open('temp.html', 'w') as f:
            #    f.write(resp.text)

            pno = 1
            sheet_list = []
            while True:
                check_for_error(resp)
                sheet_soup = BeautifulSoup(resp.text, 'html.parser')
                sheet_table = sheet_soup.find('table', { 'id': 'ContentPlaceHolder1_GridView1' })
                if sheet_table is None:
                    break
                rows = sheet_table.find_all('tr', recursive=False)
                pager_row = None
                for row in rows[1:]:
                    if row.find('table') is not None:
                        pager_row = row
                        continue
                    cols = row.find_all('td')
                    if len(cols) < 3:
                        continue
                    sheet_no = cols[1].text.strip()
                    if sheet_no == '':
                        continue
                    sheet_list.append(sheet_no)

                next_pno = pno + 1
                has_next_page = False
                if pager_row is None:
                    logging.info(f'No more pages for district {dv}, state {v}')
                    break
                tds = pager_row.find_all('td')
                pnos = []
                has_dotdot = False
                has_last = False
                for td in tds:
                    if td.find('td') is not None:
                        continue
                    txt = td.text.strip()
                    if txt == '...':
                        has_dotdot = True
                        continue
                    if txt == 'Last':
                        has_last = True
                        continue
                    try:
                        x = int(txt)
                        pnos.append(x)
                    except Exception:
                        pass

                if next_pno in pnos:
                    has_next_page = True
                elif has_dotdot and has_last and len(pnos) > 0 and next_pno == max(pnos) + 1:
                    has_next_page = True

                if not has_next_page:
                    logging.info(f'No more pages for district {dv}, state {v}')
                    break

                form_data = get_form_data(sheet_soup)
                form_data.update({
                    'ctl00$ContentPlaceHolder1$ddlFormateTyoe': 'pdf',
                    'ctl00$ContentPlaceHolder1$txtSheetNumber': '',
                    'ctl00$ContentPlaceHolder1$ddlstate': k,
                    'ctl00$ContentPlaceHolder1$ddldist': dk,
                    'ctl00$ContentPlaceHolder1$ddlProductsType': 'pdf',
                    '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$GridView1',
                    '__EVENTARGUMENT': f'Page${next_pno}',
                })
                time.sleep(DELAY)
                logging.info(f'Getting the sheet listing page {next_pno} for district {dv}, state {v}')
                resp = session.post(sheet_picker_url, headers=headers, data=form_data)
                if not resp.ok:
                    raise Exception(f'Unable to post to get sheet listing page {next_pno} for district {dv}, state {v}')
                pno = next_pno

            logging.info(f'Found {len(sheet_list)} sheets for district {dv}, state {v}')
            sheet_list_file = Path(list_data_dir) / v / dv / 'sheets.txt'
            sheet_list_file.parent.mkdir(parents=True, exist_ok=True)
            sheet_list_file.write_text('\n'.join(sheet_list) + '\n')
            dist_done_file.write_text('done')
        state_done_file.write_text('done')




if __name__ == '__main__':
    setup_logging(logging.INFO)

    #if not CAPTCHA_MANUAL:
    #    check_captcha_models(captcha_model_dir)


    #done_sheets = set()
    #force_map_tried = {}
    #otp_from_pb = True
    #typ = 'NHP'
    #geojson = json.loads(Path('data/index.geojson').read_text())
    #features = geojson['features']
    ##extra_sheet_list = Path('data/extra_himachal.txt').read_text().split('\n')
    ##extra_sheet_list = Path('data/extra_uk.txt').read_text().split('\n')
    ##extra_sheet_list = Path('data/extra_nagaland.txt').read_text().split('\n')
    ##extra_sheet_list = Path('data/extra_arunachal.txt').read_text().split('\n')
    ##extra_sheet_list = Path('data/extra_jk.txt').read_text().split('\n')
    ##extra_sheet_list = Path('data/extras_ladakh_in.txt').read_text().split('\n')
    ##extra_sheet_list = Path('data/extra_wb.txt').read_text().split('\n')
    #extra_sheet_list = Path('data/extra_unprobed.txt').read_text().split('\n')
    #extra_sheet_list = [ x.strip() for x in extra_sheet_list if x.strip() != '' ]
    #sheet_list = []
    #sheet_list.extend(extra_sheet_list)
    #sheet_list.extend([ f['properties']['id'] for f in features ])
    #sheet_list = Path('data/sheet_nos.txt').read_text().split('\n')
    #sheet_list = [ x.strip() for x in sheet_list if x.strip() != '' ]
    scrape()

