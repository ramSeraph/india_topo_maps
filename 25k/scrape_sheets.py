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

def scrape(phone_num, password, otp_from_pb, typ, sheet_list):
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
        key = 'ctl00$ContentPlaceHolder1$ListViewSingleProduct$ctrl1$Button3'

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
    soup = BeautifulSoup(resp.text, 'html.parser')
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
    resp = session.post(sheet_picker_url, headers=headers, data=form_data)
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
        out_unavailable_file = out_file.with_suffix('.pdf.unavailable')
        out_html_file = out_file.with_suffix('.html')
        if out_file.exists() or out_unavailable_file.exists() or out_html_file.exists():
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
        resp = session.post(sheet_picker_url, headers=headers, data=form_data)
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
        resp = session.post(sheet_picker_url, headers=headers, data=form_data)
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
        resp = session.post(resp.url, headers=new_headers, data=form_data)
        if not resp.ok:
            raise Exception(f'Unable to post to place order for sheet {sheet_no}')

        try:
            check_for_error(resp)
        except KnownException:
            logging.warning(f'Failed to place order for sheet {sheet_no}, marking as unavailable')
            out_unavailable_file.write_text('Sheet not available')
            done_count += 1
            raise DelayedRetriableException('Unable to place order, trying again')
            continue

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

        check_for_error(resp)
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
        check_for_error(resp, err_file=out_file.with_suffix('.html'))
        zip_file_contents = resp.content
        # decode the zip file and locate the pdf inside it
        if resp.headers.get('content-type', '').lower() != 'application/x-zip-compressed':
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
            with zf.open(pdf_file_name) as pdf_f, open(out_file, 'wb') as out_f:
                shutil.copyfileobj(pdf_f, out_f)
        logging.info(f'Sheet {sheet_no} written to {out_file}')
        done_count += 1


    return True



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

 
def scrape_wrap(otp_from_pb, typ, sheet_list):
    secrets_map = get_secrets()
    #tried_users = get_tried_users()
    secrets_map = {k:v for k,v in secrets_map.items()}
    total_count = len(secrets_map)
    s_items = list(secrets_map.items())
    while True:
        phone_num, password = s_items[0]
        try:
            ret = scrape(phone_num, password, otp_from_pb, typ, sheet_list)
            return
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
    import sys
    sheets_fname = sys.argv[1]
    setup_logging(logging.INFO)

    if not CAPTCHA_MANUAL:
        check_captcha_models(captcha_model_dir)


    done_sheets = set()
    force_map_tried = {}
    otp_from_pb = True
    typ = 'NHP'
    #geojson = json.loads(Path('data/index.geojson').read_text())
    #features = geojson['features']
    #extra_sheet_list = Path('data/extra_unprobed.txt').read_text().split('\n')
    #extra_sheet_list = [ x.strip() for x in extra_sheet_list if x.strip() != '' ]
    #sheet_list = []
    #sheet_list.extend(extra_sheet_list)
    #sheet_list.extend([ f['properties']['id'] for f in features ])
    sheet_list = Path(sheets_fname).read_text().split('\n')
    sheet_list = [ x.strip() for x in sheet_list if x.strip() != '' ]
    scrape_wrap(otp_from_pb, typ, sheet_list)

