from pathlib import Path
import re

sheet_nos = set()
for p in Path('data/list').rglob('**/sheets.txt'):
    lines = p.read_text(encoding='utf-8').splitlines()
    for line in lines:
        line = line.strip()
        if line == '2' or line == '':
            continue
        # 83K7NW
        match = re.match(r'^([0-9]{2,3})([A-P])([0-9]{1,2})([NS][EW])$', line)
        if match:
            sheet_no = f"{match.group(1)}{match.group(2)}_{match.group(3)}_{match.group(4)}"
            sheet_nos.add(sheet_no)
            continue
        print(f"Unrecognized line in {p}: {line}")

with open('data/sheet_nos.txt', 'w') as f:
    for sheet_no in sorted(sheet_nos):
        f.write(f"{sheet_no}\n")


