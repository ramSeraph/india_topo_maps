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

def download_sheet(sheet_no, input_name, soup, headers, url, state_id, dist_id):
    out_file = Path(raw_data_dir) / f'{sheet_no}.pdf'

    out_unavailable_file = out_file.with_suffix('.pdf.unavailable')
    out_html_file = out_file.with_suffix('.html')
    if out_file.exists() or out_unavailable_file.exists() or out_html_file.exists():
        logging.info(f'Skipping sheet {sheet_no}, already downloaded')
        return

    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
        'ctl00$ContentPlaceHolder1$ddlTownCoalfield': str(dist_id),
        'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': 'pdf',
        input_name: 'on',
        'ctl00$ContentPlaceHolder1$btnOkmulitySelects': 'OK',
        'ctl00$ContentPlaceHolder1$ddlstate': '0',
        'ctl00$ContentPlaceHolder1$ddldist': '0',
    })
    time.sleep(DELAY)
    logging.info(f'Selecting sheet {sheet_no}')
    resp = session.post(url, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to select sheet {sheet_no}')

    check_for_error(resp)
    form_data = get_form_data(BeautifulSoup(resp.text, 'html.parser'))
    form_data.update({
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$lbtnMultiAddToCard',
        'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
        'ctl00$ContentPlaceHolder1$ddlTownCoalfield': str(dist_id),
        'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': 'pdf',
        input_name: 'on',
        'ctl00$ContentPlaceHolder1$ddlstate': '0',
        'ctl00$ContentPlaceHolder1$ddldist': '0',
    })
    time.sleep(DELAY)
    logging.info(f'Adding sheet {sheet_no} to cart')
    resp = session.post(resp.url, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to add sheet {sheet_no} to cart')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ImageButton1',
        'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
        'ctl00$ContentPlaceHolder1$ddlTownCoalfield': str(dist_id),
        'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': 'pdf',
        'ctl00$ContentPlaceHolder1$btnViewCart': 'View Cart',
        input_name: 'on',
        'ctl00$ContentPlaceHolder1$ddlstate': '0',
        'ctl00$ContentPlaceHolder1$ddldist': '0',
    })
    time.sleep(DELAY)
    logging.info(f'viewing cart for sheet {sheet_no}')
    resp = session.post(resp.url, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to go to cart to download sheet {sheet_no}')

    new_headers = headers.copy()
    new_headers['referer'] = resp.url
    form_data = get_form_data(BeautifulSoup(resp.text, 'html.parser'))
    form_data.update({
        'ctl00$ContentPlaceHolder1$btnplaceorder': 'Place Order',
        'ctl00$ContentPlaceHolder1$HiddenField1': ''
    })

    time.sleep(DELAY)
    logging.info(f'Placing order for sheet {sheet_no}')
    resp = session.post(resp.url, headers=new_headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to place order for sheet {sheet_no}')

    try:
        check_for_error(resp)
    except KnownException:
        out_unavailable_file.write_text('unavailable')
        logging.info(f'Sheet {sheet_no} marked unavailable')
        #return
        raise DelayedRetriableException('Sheet unavailable')

    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$btnSubmitPrivateIndenter': 'I Agree',
        'ctl00$ContentPlaceHolder1$HiddenField1': ''
    })
    new_headers['referer'] = resp.url
    time.sleep(DELAY)
    logging.info(f'Agree to terms and conditions for sheet {sheet_no}')
    resp = session.post(resp.url, headers=new_headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to agree to T&C for sheet {sheet_no}')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$gvCustomers$ctl02$btnProceedDownload': 'Proceed for Download',
        'ctl00$ContentPlaceHolder1$HiddenField1': ''
    })
    new_headers['referer'] = resp.url
    logging.info(f'Proceeding to download for sheet {sheet_no}')

    time.sleep(DELAY)
    resp = session.post(resp.url, headers=new_headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to proceed to download for sheet {sheet_no}')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$gvOrders$ctl02$btnRequest': 'Request',
        'ctl00$ContentPlaceHolder1$HiddenFieldOrder': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldpointID': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldMasterCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldStateCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldDistrictCode': '',
    })
    new_headers['referer'] = resp.url
    time.sleep(DELAY)
    logging.info(f'Requesting download for sheet {sheet_no}')
    resp = session.post(resp.url, headers=new_headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to request download for sheet {sheet_no}')

    check_for_error(resp)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$gvOrders$ctl02$btnGenerateDownloadLink': 'Generate Download Link',
        'ctl00$ContentPlaceHolder1$HiddenFieldOrder': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldpointID': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldMasterCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldStateCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldDistrictCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldProductCode': '',
    })
    new_headers['referer'] = resp.url
    time.sleep(DELAY)
    logging.info(f'Generating download link for sheet {sheet_no}')
    resp = session.post(resp.url, headers=new_headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to generate download link for sheet {sheet_no}')

    try:
        check_for_error(resp)
    except KnownException:
        out_unavailable_file.write_text('unavailable')
        logging.info(f'Sheet {sheet_no} marked unavailable')
        #return
        raise DelayedRetriableException('Sheet unavailable')

    soup = BeautifulSoup(resp.text, 'html.parser')
    form_data = get_form_data(soup)
    form_data.update({
        'ctl00$ContentPlaceHolder1$gvOrders$ctl02$btnDownloadMap': 'Download',
        'ctl00$ContentPlaceHolder1$HiddenFieldOrder': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldpointID': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldMasterCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldStateCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldDistrictCode': '',
        'ctl00$ContentPlaceHolder1$HiddenFieldProductCode': '',
    })
    new_headers['referer'] = resp.url
    time.sleep(DELAY)
    logging.info(f'Downloading sheet {sheet_no}')
    resp = session.post(resp.url, headers=new_headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to post to download sheet {sheet_no}')

    try:
        check_for_error(resp)
    except KnownException:
        out_unavailable_file.write_text('unavailable')
        logging.info(f'Sheet {sheet_no} marked unavailable')
        #return
        raise DelayedRetriableException('Sheet unavailable')

    zip_file_contents = resp.content
    # decode the zip file and locate the pdf inside it
    if resp.headers.get('content-type', '').lower() != 'application/x-zip-compressed':
        raise DelayedRetriableException('Unable to get zip file')

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
        with zf.open(pdf_file_name) as pdf_f, open(out_file, 'wb') as out_f:
            shutil.copyfileobj(pdf_f, out_f)
    logging.info(f'Sheet {sheet_no} written to {out_file}')



def scrape(phone_num, password, otp_from_pb, typ):
    global done_sheets
    global force_map_tried

    login_wrap(phone_num, password, otp_from_pb)

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
    if typ == 'NHP':
        key = 'ctl00$ContentPlaceHolder1$ListViewSingleProduct$ctrl1$Button4'
    else:
        key = 'ctl00$ContentPlaceHolder1$ListViewSingleProduct$ctrl0$Button4'

    form_data.update({
        key: 'Click to Buy',
        'ctl00$ContentPlaceHolder1$rblFormats': 'All',
        'ctl00$ContentPlaceHolder1$rblDigitalProduct': '12',
    })

    logging.info(f'Navigating to the {typ} Product Specification page')
    resp = session.post(dp_page, headers=headers, data=form_data)
    if not resp.ok:
        raise Exception(f'Unable to navigate to the {typ} Product Specification page')

    check_for_error(resp)
    state_soup = BeautifulSoup(resp.text, 'html.parser')

    select = state_soup.find('select', { 'id': 'ContentPlaceHolder1_ddlstatelist' })
    states = select.find_all('option')
    state_map = { x['value']: x.text for x in states if x['value'] != '0' }

    state_map_file = Path(data_dir) / 'list' / 'state_map.json'
    state_map_file.parent.mkdir(parents=True, exist_ok=True)
    state_map_file.write_text(json.dumps(state_map, indent=2))

    sheet_picker_url = resp.url

    for state_id, state_name in state_map.items():
        state_dir = Path(data_dir) / 'list' / str(state_id)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_done_file = state_dir / 'done.txt'
        if state_done_file.exists():
            logging.info(f'Skipping state {state_name}, already done')
            continue

        logging.info(f'Processing state {state_name}')
        form_data = get_form_data(state_soup)
        form_data.update({
            '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlstatelist',
            'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
            'ctl00$ContentPlaceHolder1$ddlTownCoalfield': '0',
            'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': '',
            'ctl00$ContentPlaceHolder1$ddlstate': '0',
            'ctl00$ContentPlaceHolder1$ddldist': '0',
        })
        logging.info(f'Getting the district listing for state {state_name}')
        resp = session.post(sheet_picker_url, headers=headers, data=form_data)
        if not resp.ok:
            raise Exception(f'Unable to post to get district listing for state {state_name}')

        check_for_error(resp)
        dist_soup = BeautifulSoup(resp.text, 'html.parser')

        select = dist_soup.find('select', { 'id': 'ContentPlaceHolder1_ddlTownCoalfield' })
        dists = select.find_all('option')
        dist_map = { x['value']: x.text for x in dists if x['value'] != '0' }

        dist_map_file = state_dir / 'dist_map.json'
        dist_map_file.write_text(json.dumps(dist_map, indent=2))

        for dist_id, dist_name in dist_map.items():
            dist_dir = state_dir / str(dist_id)
            dist_dir.mkdir(parents=True, exist_ok=True)
            dist_done_file = dist_dir / 'done.txt'
            if dist_done_file.exists():
                logging.info(f'Skipping district {dist_name}, already done')
                continue

            logging.info(f'Processing district {dist_name}')
            form_data = get_form_data(dist_soup)
            form_data.update({
                '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlTownCoalfield',
                'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
                'ctl00$ContentPlaceHolder1$ddlTownCoalfield': str(dist_id),
                'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': '',
                'ctl00$ContentPlaceHolder1$ddlstate': '0',
                'ctl00$ContentPlaceHolder1$ddldist': '0',
            })
            logging.info(f'Changing to district {dist_name}')
            resp = session.post(sheet_picker_url, headers=headers, data=form_data)
            if not resp.ok:
                raise Exception(f'Unable to post to get sheet listing for district {dist_name}')
     
            check_for_error(resp)
            soup = BeautifulSoup(resp.text, 'html.parser')
            form_data = get_form_data(soup)


            form_data.update({
                '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$ddlformatTypeproducts',
                'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
                'ctl00$ContentPlaceHolder1$ddlTownCoalfield': str(dist_id),
                'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': 'pdf',
                'ctl00$ContentPlaceHolder1$ddlstate': '0',
                'ctl00$ContentPlaceHolder1$ddldist': '0',
            })
            sheet_picker_url = resp.url
            logging.info('Change to pdf listing')
            resp = session.post(sheet_picker_url, headers=headers, data=form_data)
            if not resp.ok:
                raise Exception('Unable to post to change to pdf listing')
       
            pno = 1
            while True:
                check_for_error(resp)
                sheet_soup = BeautifulSoup(resp.text, 'html.parser')

                table = sheet_soup.find('table', { 'id': 'ContentPlaceHolder1_GridViewPopup' })
                if table is None:
                    logging.info(f'No sheets available for district {dist_name}, marking done')
                    dist_done_file.write_text('done')
                    continue

                rows = table.find_all('tr', recursive=False)
                sheet_list = []
                pager_row = None
                for row in rows[1:]:
                    if row.find('table') is not None:
                        pager_row = row
                        continue
                    cols = row.find_all('td')
                    if len(cols) < 4:
                        continue
                    sheet_num = cols[1].text.strip()
                    input = cols[3].find('input')
                    if input is None:
                        continue
                    input_name = input.get('name')
                    sheet_list.append((sheet_num, input_name))

                for sheet in sheet_list:
                    download_sheet(sheet[0], sheet[1], sheet_soup, headers, resp.url, state_id, dist_id)


                #sheet_list_file = dist_dir / f'{pno}.txt'
                #sheet_list_file.write_text('\n'.join(sheet_list))
                next_pno = pno + 1
                has_next_page = False
                if pager_row is None:
                    logging.info(f'No more pages for district {dist_name}')
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
                        v = int(txt)
                        pnos.append(v)
                    except Exception:
                        pass

                if next_pno in pnos:
                    has_next_page = True
                elif has_dotdot and has_last and len(pnos) > 0 and next_pno == max(pnos) + 1:
                    has_next_page = True

                if not has_next_page:
                    logging.info(f'No more pages for district {dist_name}')
                    break

                logging.info(f'Getting page {pno} for district {dist_name}')
                form_data = get_form_data(sheet_soup)
                form_data.update({
                    '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$GridViewPopup',
                    '__EVENTARGUMENT': f'Page${next_pno}',
                    'ctl00$ContentPlaceHolder1$ddlstatelist': str(state_id),
                    'ctl00$ContentPlaceHolder1$ddlTownCoalfield': str(dist_id),
                    'ctl00$ContentPlaceHolder1$ddlformatTypeproducts': 'pdf',
                    'ctl00$ContentPlaceHolder1$ddlstate': '0',
                    'ctl00$ContentPlaceHolder1$ddldist': '0',
                })
                #time.sleep(DELAY)
                logging.info(f'Getting the sheet listing page {pno} for district {dist_name}')
                resp = session.post(resp.url, headers=headers, data=form_data)
                if not resp.ok:
                    raise Exception(f'Unable to post to get sheet listing page {pno} for district {dist_name}')
                pno = next_pno

            dist_done_file.write_text('done')
        state_done_file.write_text('done')

    return False


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

 
def scrape_wrap(otp_from_pb, typ):
    secrets_map = get_secrets()
    #tried_users = get_tried_users()
    secrets_map = {k:v for k,v in secrets_map.items()}
    total_count = len(secrets_map)
    s_items = list(secrets_map.items())
    while True:
        phone_num, password = s_items[0]
        try:
            ret = scrape(phone_num, password, otp_from_pb, typ)
            if not ret:
                break
        except (KnownException, DelayedRetriableException) as ke:
            logger.warning('Known Exception for this user..')
            time.sleep(60)
            saved_cookie_file = Path(f'data/cookies/saved_cookies.{phone_num}.pkl')
            saved_cookie_file.unlink(missing_ok=True)
            reset_session()
            # unlink cookie file
            #tried_users.append(phone_num)
            #update_tried_users(tried_users)
            #session = requests.session()
        except Exception as ex:
            logger.error('Some Exception happened, cannot continue')
            logger.exception(ex)
            raise ex


if __name__ == '__main__':
    setup_logging(logging.INFO)

    if not CAPTCHA_MANUAL:
        check_captcha_models(captcha_model_dir)


    done_sheets = set()
    force_map_tried = {}
    otp_from_pb = True
    typ = 'CMPDI'
    #geojson = json.loads(Path('data/index.geojson').read_text())
    #features = geojson['features']
    #sheet_list = [ f['properties']['id'] for f in features ]
    scrape_wrap(otp_from_pb, typ)

