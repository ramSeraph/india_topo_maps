
from pprint import pprint

main_map = [ 
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1],
    [1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1],
]

num_cols = len(main_map[0])
num_rows = len(main_map)

start_lon = 44
start_lat = 40

top_left_corners = {}

count = 1
for col in range(num_cols):
    for row in range(num_rows):
        if main_map[row][col] != 0:
            top_left_corners[count] = ((col*4) + start_lon, start_lat - (row*4))
            count += 1
pprint(top_left_corners)

# assume indexing is like this
# A E I M
# B F J N
# C G K O
# D H L P

# now given a sheet number like 72H return the corners
def get_sheet_tl_253k(sheet_no):

    number = sheet_no[:-1]
    number = int(number)

    letter = sheet_no[-1]
    if letter not in 'ABCDEFGHIJKLMNOP':
        raise ValueError('Invalid letter')
    
    if number not in top_left_corners:
        raise ValueError('Invalid sheet number')

    number_top_left = top_left_corners[number]
    
    letter_index = ord(letter) - ord('A')
    col_offset = letter_index % 4
    row_offset = letter_index // 4
    tl = (number_top_left[0] + (col_offset * 1), number_top_left[1] - (row_offset * 1))
    return tl

def get_sheet_box_253k(sheet_no):
    tl = get_sheet_tl_253k(sheet_no)
    bl = (tl[0], tl[1] - 1)
    tr = (tl[0] + 1, tl[1])
    br = (tr[0], bl[1])
    return [ tl, tr, br, bl, tl ]


def get_sheet_box_126k(sheet_no):
    parts = sheet_no.split('_')
    if len(parts) != 2:
        raise ValueError('Invalid sheet number format')
    part_253k = parts[0]
    part_quarter = parts[1]
    if part_quarter not in ['NW', 'NE', 'SW', 'SE']:
        raise ValueError('Invalid quarter part')
    
    tl_253k = get_sheet_tl_253k(part_253k)

    if part_quarter == 'NW':
        tl = tl_253k
    elif part_quarter == 'NE':
        tl = (tl_253k[0] + 0.5, tl_253k[1])
    elif part_quarter == 'SW':
        tl = (tl_253k[0], tl_253k[1] - 0.5)
    elif part_quarter == 'SE':
        tl = (tl_253k[0] + 0.5, tl_253k[1] - 0.5)
    bl = (tl[0], tl[1] - 0.5)
    tr = (tl[0] + 0.5, tl[1])
    br = (tr[0], bl[1])

    return [ tl, tr, br, bl, tl ]

def get_sheet_box_63k(sheet_no):
    parts = sheet_no.split('_')
    if len(parts) != 2:
        raise ValueError('Invalid sheet number format')
    part_253k = parts[0]
    part_inner = parts[1]
    number = int(part_inner)
    if number < 1 or number > 16:
        raise ValueError('Invalid inner part number')
    
    tl_253k = get_sheet_tl_253k(part_253k)
    inner_col = (number - 1) % 4
    inner_row = (number - 1) // 4
    tl = (tl_253k[0] + (inner_col * 0.25), tl_253k[1] - (inner_row * 0.25))
    bl = (tl[0], tl[1] - 0.25)
    tr = (tl[0] + 0.25, tl[1])
    br = (tr[0], bl[1])
    return [ tl, tr, br, bl, tl ]


