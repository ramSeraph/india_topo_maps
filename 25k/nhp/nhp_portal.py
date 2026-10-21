import re


def get_error_alert(soup):
    """Read server-emitted error alerts, excluding commented browser warnings."""
    for script in soup.find_all('script'):
        for match in re.finditer(r'''^\s*alert\(\s*(['"])(.*?)\1\s*\)''', script.get_text(), re.MULTILINE):
            message = match[2]
            if re.search(r'error|not available|not exist|not found|invalid|unable|no record|no data', message, re.IGNORECASE):
                return message
    return None


def normalize_sheet_no(value):
    text = str(value).strip().upper().removesuffix('.PDF')
    text = re.sub(r'[\s_/-]+', '', text)
    match = re.fullmatch(r'(\d{2,3}[A-P])0*(\d{1,2})([NS][EW])', text)
    if match is None or not 1 <= int(match[2]) <= 16:
        raise ValueError(f'Invalid NHP sheet number: {value!r}')
    return f'{match[1]}_{int(match[2])}_{match[3]}'


def get_product_selection(soup, product='NHP'):
    """Use the current submit control from the named product's card."""
    matches = []
    for card in soup.select('.cardsa'):
        title = card.find('span', id=re.compile(r'_Label3_\d+$'))
        if title is None or not re.search(rf'\b{re.escape(product)}\b', title.get_text(), re.IGNORECASE):
            continue
        button = card.find('input', attrs={'type': 'submit', 'value': 'Click to Buy'})
        if button is not None and button.get('name'):
            matches.append(button)
    if len(matches) != 1:
        raise RuntimeError(f'Expected one {product} product button, found {len(matches)}')
    button = matches[0]
    return {button['name']: button['value']}


def require_pdf_picker(soup):
    formats = soup.find('select', id='ContentPlaceHolder1_ddlFormateTyoe')
    if formats is None or formats.find('option', value='pdf') is None:
        raise RuntimeError('SOI did not open a product page offering PDF downloads')


def get_submit_control(soup, control, sheet_no=None, required=True):
    buttons = soup.find_all('input', attrs={
        'type': 'submit', 'name': re.compile(rf'\${re.escape(control)}$'),
    })
    for button in buttons:
        if button.has_attr('disabled'):
            continue
        if sheet_no is not None:
            row = button.find_parent('tr')
            normalize = lambda text: re.sub(r'[^A-Z0-9]', '', text.upper())
            if row is None or not any(normalize(cell.get_text(strip=True)) == normalize(sheet_no)
                                      for cell in row.find_all('td')):
                continue
        # SOI lists the newest order first, including repeat orders for a sheet.
        return {button['name']: button.get('value', '')}
    if required:
        raise RuntimeError(f'SOI did not offer {control} for {sheet_no or "this order"}')
    return None
