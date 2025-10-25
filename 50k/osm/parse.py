# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pdfminer-six",
#     "pypdf",
#     "topo-map-processor[parse]",
# ]
#
# ///


import os
import json
import shutil
import subprocess
from pathlib import Path

from pdfminer.image import ImageWriter
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfpage import PDFTextExtractionNotAllowed
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTImage
from pdfminer.pdftypes import resolve_all, PDFObjRef, PDFNotImplementedError

from pypdf import PdfReader

import cv2
#from imgcat import imgcat
import numpy as np

from topo_map_processor.processor import TopoMapProcessor, LineRemovalParams

def get_images(layout):
    imgs = []
    if isinstance(layout, LTImage):
        imgs.append(layout)

    objs = getattr(layout, '_objs', [])
    for obj in objs:
        imgs.extend(get_images(obj))
    return imgs

class SOIProcessor(TopoMapProcessor):

    def __init__(self, filepath, extra, index_map):
        super().__init__(filepath, extra, index_map)
        self.flavor = None
        self.warp_jpeg_export_quality = extra.get('warp_jpeg_export_quality', 100)
        self.jpeg_export_quality = extra.get('jpeg_export_quality', 50)
        self.ext_thresh_ratio = extra.get('ext_thresh_ratio', 20.0 / 18000.0)
        self.find_line_iter = extra.get('find_line_iter', 1)
        self.find_line_scale = extra.get('find_line_scale', 3)
        self.pdf_rotate = extra.get('pdf_rotate', 0)
        self.use_bbox_area = extra.get('use_bbox_area', True)
        self.auto_rotate_thresh = extra.get('auto_rotate_thresh', 0)
        self.corner_overrides = extra.get('corner_overrides', None)
        self.grid_lines = extra.get('grid_lines', None)
        self.poly_approx_factor = extra.get('poly_approx_factor', 0.001)
        self.cwidth = extra.get('cwidth', 1)
        self.collar_erode = extra.get('collar_erode', 0)
        self.map_area_ratio_thresh = extra.get('map_area_ratio_thresh', 0.4)
        #self.map_area_ratio_thresh = extra.get('map_area_ratio_thresh', 0.5) # old value which was used for all files not in new_set.txt
        self.max_corner_angle_diff = extra.get('max_corner_angle_diff', 7) 
        #self.max_corner_angle_diff = extra.get('max_corner_angle_diff', 5) # old value which was used for all files not in new_set.txt

        self.should_remove_grid_lines = extra.get('should_remove_grid_lines', True)
        self.grid_bounds_check_buffer_ratio = extra.get('grid_bounds_check_buffer_ratio', 40.0 / 7000.0)
        self.remove_line_buf_ratio = extra.get('remove_line_buf_ratio', 6.0 / 12980.0)
        self.remove_line_blur_buf_ratio = extra.get('remove_blur_buf_ratio', 30.0 / 12980.0)
        self.remove_line_blur_kern_ratio = extra.get('remove_blur_kern_ratio', 19.0 / 12980.0)
        self.remove_line_blur_repeat = extra.get('remove_line_blur_repeat', 0)

        self.min_corner_dist_ratio = extra.get('min_corner_dist_ratio', 0.3)
        self.max_corner_dist_ratio = extra.get('max_corner_dist_ratio', 0.75)
        #self.max_corner_angle_diff = extra.get('max_corner_angle_diff', 5)
        self.max_corner_angle_diff_cutoff = extra.get('max_corner_angle_diff_cutoff', 20)
        self.remove_corner_text = extra.get('remove_corner_text', False)

        self.band_color = extra.get('band_color', None)
        self.band_color_choices = extra.get('band_color_choices', [['pinkish'], ['red1', 'red2'], ['not_white']])
        self.line_color = extra.get('line_color', None)
        self.line_color_choices = extra.get('line_color_choices', ['black', ['black', 'greyish'], ['not_white']])

        self.color_map.update({
            'pink': ((140, 74, 76), (166, 255, 255)),
            'pinkish': ((130, 40, 76), (170, 255, 255)),
            'greyish': ((0, 0, 50), (179, 130, 145)),
            'green': ((50, 100, 100), (70, 255, 255)),
            'red1': ((0, 50, 50), (10, 255, 255)),
            'red2': ((165, 50, 50), (180, 255, 255)),
            'blue': ((100, 50, 0), (140, 255, 255)),
        })

        self.index_box = extra.get('index_override', self.index_box)



    def get_resolution(self):
        return "auto"

    def get_crs_proj(self):
        return "EPSG:4326"

    def get_intersection_point(self, img, direction, anchor_angle):

        if self.line_color is not None:
            line_color_choices = [self.line_color]
        else:
            line_color_choices = self.line_color_choices

        ip = None
        for line_color in line_color_choices:
            try:
                min_expected_points = 1
                expect_band_count = 0
                remove_text = self.remove_corner_text
                ip = self.get_nearest_intersection_point(img, direction, anchor_angle,
                                                         line_color, remove_text, expect_band_count,
                                                         self.find_line_scale, self.find_line_iter,
                                                         self.max_corner_dist_ratio, self.min_corner_dist_ratio,
                                                         min_expected_points, self.max_corner_angle_diff,
                                                         self.max_corner_angle_diff_cutoff)
                return ip
            except Exception as ex:
                print(f'Failed to nearest intersection: {ex}')

        if ip is None:
            raise Exception('Failed to find intersection point')

        return ip


    def locate_grid_lines(self):
        full_img = self.get_full_img()
        h,w = full_img.shape[:2]
        bounds_check_buffer = int(self.grid_bounds_check_buffer_ratio * h)

        gcps = self.get_gcps()
        transformer = self.get_transformer_from_gcps(gcps)

        lines, lines_xy = self.locate_grid_lines_using_trasformer(transformer, 24, 1, bounds_check_buffer)
        #print(f'found {len(lines)} grid lines')
        #from pprint import pprint
        #pprint(lines)
        params = LineRemovalParams(
            self.remove_line_buf_ratio,
            self.remove_line_blur_buf_ratio,
            self.remove_line_blur_kern_ratio,
            self.remove_line_blur_repeat
        )
        return [ (line, params) for line in lines ]

    def get_full_img_file(self):
        workdir = self.get_workdir()
        return workdir / 'full.jpg'

    def image_pdf_extract(self):
        document = self.get_pdf_doc()
     
        if not document.is_extractable:
            raise PDFTextExtractionNotAllowed(
                    "Text extraction is not allowed"
            )
        img_writer = ImageWriter('.')
        rsrcmgr = PDFResourceManager(caching=True)
        device = PDFPageAggregator(rsrcmgr, laparams=None)
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        page_info = {}
        pno = 0
        for page in PDFPage.create_pages(document):
            if pno > 0:
                raise Exception('only one page expected')
            interpreter.process_page(page)
            layout = device.get_result()
            page_info = {}
            page_info['layout'] = layout
            images = get_images(layout)
            if len(images) > 1:
                raise Exception('Only one image expected')
            image = images[0]
            print(image)
            print(image.colorspace)

            # fix to pdfminer bug
            if len(image.colorspace) == 1 and isinstance(image.colorspace[0], PDFObjRef):
                image.colorspace = resolve_all(image.colorspace[0])
                if not isinstance(image.colorspace, list):
                    image.colorspace = [ image.colorspace ]

            print(image.colorspace)
            try:
                fname = img_writer.export_image(image)
                print(f'image extracted to {fname}')
                out_filename = str(self.get_full_img_file())
                print(f'writing {out_filename}')
                if fname.endswith('.bmp') or fname.endswith('.img'):
                    # give up
                    Path(fname).unlink()
                    self.convert_pdf_to_image()
                else:
                    try:
                        res_x_str = subprocess.check_output(
                            f'identify -format "%x" {fname}', shell=True, text=True
                        ).strip()
                        res_x = int(float(res_x_str))
                    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
                        print("Could not determine resolution, assuming 300dpi and moving on")
                        shutil.move(fname, out_filename)
                    else:
                        print(f'Image resolution: {res_x} dpi')

                        if res_x == 72:
                            Path(fname).unlink()
                            self.convert_pdf_to_image()
                        elif res_x == 300:
                            shutil.move(fname, out_filename)
                        else:
                            Path(fname).unlink()
                            raise Exception(f"Unsupported image resolution {res_x} dpi, only 72 and 300 are supported.")
            except PDFNotImplementedError:
                self.convert_pdf_to_image()
            pno += 1


    def convert_pdf_to_image(self):
        inp = PdfReader(open(self.filepath, 'rb'))
        page = inp.pages[0]
        print(f'Advertised ROTATE: {page.rotation}')
        rotate = self.pdf_rotate
        print(f'ROTATE: {rotate}')
        img_filename = str(self.get_full_img_file())
        print('converting pdf to image using mupdf')
        self.run_external(f'bin/mutool draw -n data/SOI_FONTS -r 300 -c rgb -o {img_filename} {self.filepath}')
        if rotate == 90 or rotate == 270:
            print('rotating image')
            img = cv2.imread(img_filename)
            img_rotate = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE if rotate == 90 else cv2.ROTATE_90_COUNTERCLOCKWISE)
            rotate_filename = img_filename.replace('.jpg', '.rotated.jpg')
            cv2.imwrite(rotate_filename, img_rotate)
            shutil.move(rotate_filename, img_filename)



    def convert(self):
        img_file = self.get_full_img_file()
        if img_file.exists():
            print(f'file {img_file} exists.. skipping conversion')
            return
    
        flavor = self.get_flavor()
        if flavor in ['Image PDF', 'Photoshop']:
            self.image_pdf_extract()
        else:
            self.convert_pdf_to_image()


    def get_pdf_doc(self):
        self.file_fp = open(self.filepath, "rb")
        parser = PDFParser(self.file_fp)
        document = PDFDocument(parser)
        return document


    def get_flavor(self):
        if self.flavor is not None:
            return self.flavor
        workdir = self.get_workdir()
        flav_file = workdir / 'flav.txt'
        if flav_file.exists():
            self.flavor = flav_file.read_text().strip()
            return self.flavor

        document = self.get_pdf_doc()
        doc_producer = document.info[0]['Producer'].decode('utf8')
        if 'Image Conversion Plug-in' in doc_producer:
            flavor = 'Image PDF'
        elif 'Acrobat Distiller' in doc_producer:
            flavor = 'Distiller'
        elif 'PDFOut' in doc_producer:
            flavor = 'PDFOut'
        elif 'Adobe Photoshop' in doc_producer:
            flavor = 'Photoshop'
        elif 'www.adultpdf.com' in doc_producer:
            flavor = 'Adultpdf'
        elif 'GPL Ghostscript' in doc_producer:
            flavor = 'Ghostscript'
        elif 'GS PDF LIB' in doc_producer:
            flavor = 'GSPDF'
        elif 'Adobe PDF Library' in doc_producer:
            flavor = 'Microstation'
        elif 'ImageMill Imaging Library' in doc_producer:
            flavor = 'ImageMill'
        else:
            print(document.info)
            raise Exception('Unknown flavor')
 
        flav_file.parent.mkdir(parents=True, exist_ok=True)
        flav_file.write_text(flavor)
        self.flavor = flavor
        return flavor

    #def prompt1(self):
    #    pass

    def rotate(self):
        self.convert()
        super().rotate()


def get_index_map():
    index_file = Path('data/index_50k.geojson')
    if not index_file.exists():
        raise Exception('data/index_50k.geojson not found')
    data = json.loads(index_file.read_text())
    index_map = {}
    for item in data['features']:
        props = item['properties']
        id = props['id']
        geom = item['geometry']
        if geom['type'] != 'Polygon':
            raise Exception('only Polygon supported')
        coords = geom['coordinates'][0]
        index_map[id] = coords

    return index_map

def handle_65A_11(processor):
    processor.convert()
    workdir = processor.get_workdir()
    final_file = workdir / 'final.tif'
    if final_file.exists():
        print(f'{final_file} exists.. skipping')
        return

    img = processor.get_full_img()
    corners = [[1927,1010],[1907,7545],[8113,7557],[8122,1024]]

    corners_contour = np.array(corners).reshape((-1,1,2)).astype(np.int32)
    bbox = cv2.boundingRect(corners_contour)
    print(f'{bbox=}')
    nogrid_img = processor.crop_img(img, bbox)
    nogrid_file = workdir / 'nogrid.jpg'
    #full_file = converter.file_dir.joinpath('full.jpg')
    corners_file = workdir / 'corners.json'
    cv2.imwrite(str(nogrid_file), nogrid_img)
    corners_in_box = [ (c[0] - bbox[0], c[1] - bbox[1]) for c in corners ]
    print(f'{corners_in_box=}')
    processor.mapbox_corners = corners_in_box
    with open(corners_file, 'w') as f:
        json.dump(corners_in_box, f, indent = 4)
    #full_file.unlink()

    processor.georeference()
    processor.warp()
    processor.export()

def handle_55J_16(processor):
    workdir = processor.get_workdir()
    final_file = workdir / 'final.tif'
    if final_file.exists():
        print(f'{final_file} exists.. skipping')
        return

    processor.convert()
    corners = [[4445,1021],[4350,7915],[11916,8020],[12012,1125]]
    bbox = cv2.boundingRect(np.array(corners).reshape((-1,1,2)).astype(np.int32))

    full_img = processor.get_full_img()
    cropped_img = processor.crop_img(full_img, bbox)
    cropped_file = workdir / 'cropped.jpg'
    cv2.imwrite(str(cropped_file), cropped_img)
    shutil.move(str(cropped_file), str(processor.get_full_img_file()))
    processor.full_img = None
    processor.process()


def process_files():
    
    data_dir = Path('data/raw')
    
    from_list_file = os.environ.get('FROM_LIST', None)
    if from_list_file is not None:
        fnames = Path(from_list_file).read_text().split('\n')
        image_files = [ Path(f'{data_dir}/{f.strip()}') for f in fnames if f.strip() != '']
    else:
        # Find all jpg files
        print(f"Finding jpg files in {data_dir}")
        image_files = list(data_dir.glob("**/*.pdf"))
    print(f"Found {len(image_files)} jpg files")
    
    
    special_cases_file = Path(__file__).parent / 'special_cases.json'

    special_cases = {}
    if special_cases_file.exists():
        special_cases = json.loads(special_cases_file.read_text())

    #new_set = set()
    #with open('new_set.txt', 'r') as f:
    #    for line in f:
    #        new_set.add(line.strip())

    bad_files = set()
    with open('bad_files.txt', 'r') as f:
        for line in f:
            bad_files.add(line.strip())

    index_map = get_index_map()

    total = len(image_files)
    processed_count = 0
    failed_count = 0
    success_count = 0
    # Process each file
    for filepath in image_files:
        print(f'==========  Processed: {processed_count}/{total} Success: {success_count} Failed: {failed_count} processing {filepath.name} ==========')
        if filepath.name in bad_files:
            continue
        extra = special_cases.get(filepath.name, {})
        id = filepath.name.replace('.pdf', '')

        index_box = index_map.get(id, None)


        processor = SOIProcessor(filepath, extra, index_box)

        try:
            if id == '65A_11':
                handle_65A_11(processor)
            elif id == '55J_16':
                handle_55J_16(processor)
            else:
                processor.process()
            success_count += 1
        except Exception as ex:
            print(f'parsing {filepath} failed with exception: {ex}')
            failed_count += 1
            import traceback
            traceback.print_exc()
            raise
            processor.prompt()
        processed_count += 1

    print(f"Processed {processed_count} images, failed_count {failed_count}, success_count {success_count}")


if __name__ == "__main__":

    process_files()
 
