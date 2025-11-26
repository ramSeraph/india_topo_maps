# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pymupdf",
#     "topo-map-processor[parse]",
#     "shapely",
# ]
#
# ///


import os
import json
import time
import subprocess
import traceback
from pathlib import Path
from pprint import pprint
from collections import namedtuple

import cv2
import pymupdf
import numpy as np
from shapely.geometry import LineString

from topo_map_processor.processor import TopoMapProcessor, LineRemovalParams

GRATICULE_LAYER_NAME_PREFIX1 = "Graticle_Line"
GRATICULE_LAYER_NAME_PREFIX2 = "Graticule"
GRATICULE_LAYER_NAME_PREFIX3 = "IndiaGridpro_25K"
GRATICULE_LAYER_NAME_PREFIX4 = "GRATICAL"
GRATICULE_LAYER_NAME_PREFIXES = [GRATICULE_LAYER_NAME_PREFIX1, GRATICULE_LAYER_NAME_PREFIX2, GRATICULE_LAYER_NAME_PREFIX3, GRATICULE_LAYER_NAME_PREFIX4]
OTHER_LAYER_NAME_PREFIX = "Other"
DPI = 300

BLUE_LINES_MIN_LINE_SCALE = 32
BLACK_LINES_MIN_LINE_SCALE = 16
BLACK_COLOR_TOL = 0.1
BLUE_COLOR_TOL = 0.1

# create a point namedtuple
Point = namedtuple('Point', ['x', 'y'])

def run_external(cmd):
    print(f'running cmd - {cmd}')
    start = time.time()
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    end = time.time()
    print(f'STDOUT: {res.stdout}')
    print(f'STDERR: {res.stderr}')
    print(f'command took {end - start} secs to run')
    if res.returncode != 0:
        raise Exception(f'command {cmd} failed with exit code: {res.returncode}')

# assumes some ordering of the points in the lines, and the lines themselves
def get_line_intersection_parallel(line1, line2, direction, tolerance=0.0):
    lines = [line1, line2]
    if direction == 'vertical':
        lines.sort(key=lambda line: ((line[0].x + line[1].x)/2, line[0].y))
    else: # horizontal
        lines.sort(key=lambda line: ((line[0].y + line[1].y)/2, line[0].x))
    line1, line2 = lines

    p1, p2 = line1
    p3, p4 = line2
    
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y

    if x1 == x2 and y1 == y2:
        return None, 'empty'

    if x3 == x4 and y3 == y4:
        return None, 'empty'

    l1 = LineString( [(x1, y1), (x2, y2)] )
    l2 = LineString( [(x3, y3), (x4, y4)] )
    if l1.buffer(tolerance).intersects(l2.buffer(tolerance)):
        return ((x2 + x3)/2, (y2 + y3)/2), 'close'

    return None, 'none'

    t_dist = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    u_dist = np.sqrt((x4 - x3)**2 + (y4 - y3)**2)
    t_tol = tolerance / t_dist
    u_tol = tolerance / u_dist
     
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if den == 0:
        l1 = LineString( [(x1, y1), (x2, y2)] )
        l2 = LineString( [(x3, y3), (x4, y4)] )
        if l1.buffer(tolerance).intersects(l2.buffer(tolerance)):
            return ((x2 + x3)/2, (y2 + y3)/2), 'close'
        # check if they are very close and overlapping
        #if direction == 'vertical':
        #    #if abs(x2 - x3) < tolerance:
        #    if abs((x2 + x1)/2 - (x3 + x4)/2) < tolerance:
        #        # check if they overlap in y
        #        if y3 - y2 < tolerance and y3 > y1:
        #            return ((x2 + x3) / 2, (y2 + y3) / 2), 'overlap'
        #else:
        #    #if abs(y2 - y3) < tolerance:
        #    if abs((y1 + y2)/2 - (y3 + y4)/2) < tolerance:
        #        # check if they overlap in x
        #        if x3 - x2 < tolerance and x3 > x1:
        #            return ((x2 + x3) / 2, (y2 + y3) / 2), 'overlap'
        return None, 'parallel'
         
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
    
    if 0 - t_tol <= t <= 1 + t_tol and 0 - u_tol <= u <= 1 + u_tol:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1)), 'intersect'
        
    return None, 'none'


def get_line_intersection_perpendicular(line1, line2, tolerance=0.0, pick_only_4way=False, pick_only_4way_tolerance=5.0):
    """
    Calculates the intersection of two line segments.
    
    Args:
        line1: A tuple (p1, p2) representing the first line segment.
        line2: A tuple (p3, p4) representing the second line segment.
        
    Returns:
        A tuple (x, y) representing the intersection point, or None if the lines don't intersect.
    """
    p1, p2 = line1
    p3, p4 = line2
    
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y

    if x1 == x2 and y1 == y2:
        return None

    if x3 == x4 and y3 == y4:
        return None

    t_dist = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    u_dist = np.sqrt((x4 - x3)**2 + (y4 - y3)**2)
    t_tol = tolerance / t_dist
    u_tol = tolerance / u_dist
    
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if den == 0:
        return None
        
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
    
    # if pick_only_4way is True, only consider intersections that have extensions on both sides of the line segments

    if 0 - t_tol <= t <= 1 + t_tol and 0 - u_tol <= u <= 1 + u_tol:
        if pick_only_4way:
            t_4way_tol = pick_only_4way_tolerance / t_dist
            u_4way_tol = pick_only_4way_tolerance / u_dist
            if not (0 + t_4way_tol < t < 1 - t_4way_tol and 0 + u_4way_tol < u < 1 - u_4way_tol):
                return None
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        
    return None

def display_lines(horizontal_lines, vertical_lines, title="Lines"):
    import matplotlib.pyplot as plt

    plt.figure(figsize=(10, 10))
    for line in horizontal_lines:
        p1, p2 = line
        plt.plot([p1.x, p2.x], [p1.y, p2.y], '-')
    for line in vertical_lines:
        p1, p2 = line
        plt.plot([p1.x, p2.x], [p1.y, p2.y], '-')
    plt.title(title)
    plt.gca().set_aspect('equal', adjustable='box')
    plt.show()

def join_and_prune_lines(page, lines, direction='vertical', join_tol=1.0, join_angle_tol=1.0, line_scale=2, has_thickness=False):
    h,w = page.rect.height, page.rect.width

    lines = join_lines(lines, direction=direction, tolerance=join_tol, angle_tol=join_angle_tol, page=page, has_thickness=has_thickness)

    if direction == 'vertical':
        lines = [ line for line in lines if line[0].y - line[1].y != 0 and (h / abs(line[0].y - line[1].y)) < line_scale ]
    else:
        lines = [ line for line in lines if line[0].x - line[1].x != 0 and (w / abs(line[0].x - line[1].x)) < line_scale ]

    return lines


def get_corners_from_lines(page, vertical_lines, horizontal_lines, line_scale=2, pick_only_4way=True, join_angle_tol=1.0, join_tol=2.0):

    print(f"Found {len(vertical_lines)} vertical and {len(horizontal_lines)} horizontal lines")
    #display_lines(horizontal_lines, vertical_lines, title="Extracted Lines")

    vertical_lines = join_and_prune_lines(page, vertical_lines, direction='vertical', join_tol=join_tol, join_angle_tol=join_angle_tol, line_scale=line_scale)
    horizontal_lines = join_and_prune_lines(page, horizontal_lines, direction='horizontal', join_tol=join_tol, join_angle_tol=join_angle_tol, line_scale=line_scale)

    print(f"After joining and filtering short lines, {len(vertical_lines)} vertical and {len(horizontal_lines)} horizontal lines")
    #display_lines(horizontal_lines, vertical_lines, title="Extracted Lines")

    intersections = []
    for h_line in horizontal_lines:
        for v_line in vertical_lines:
            intersection = get_line_intersection_perpendicular(h_line, v_line, pick_only_4way=pick_only_4way, pick_only_4way_tolerance=5.0)
            if intersection:
                intersections.append(intersection)
                
    if not intersections:
        print("No intersections found.")
        return

    # Filter for unique intersection points
    unique_intersections = {}
    uniqueness_threshold = 1.0
    for point in intersections:
        is_unique = True
        for unique_point in unique_intersections:
            dist = np.sqrt((point[0] - unique_point[0])**2 + (point[1] - unique_point[1])**2)
            if dist < uniqueness_threshold:
                unique_intersections[unique_point] += 1
                is_unique = False
                break
        if is_unique:
            unique_intersections[point] = 1

    pprint('Unique intersections found:')
    pprint(unique_intersections)
    unique_intersections = [ point for point, count in unique_intersections.items() ]

    if len(unique_intersections) < 4:
        print(f"Found only {len(unique_intersections)} unique intersections, cannot determine 4 corners.")
        return

    # Find the envelope and its center
    ix, iy = zip(*unique_intersections)
    min_x, max_x = min(ix), max(ix)
    min_y, max_y = min(iy), max(iy)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    # Calculate distances from the center
    distances = [np.sqrt((x - center_x)**2 + (y - center_y)**2) for x, y in unique_intersections]
    
    # Get the four most distant points
    sorted_indices = np.argsort(distances)[-4:]
    corner_points = [unique_intersections[i] for i in sorted_indices]
    
    # Classify corner points
    # Sort by x-coordinate first to separate left and right points
    sorted_corners_by_x = sorted(corner_points, key=lambda p: p[0])
    
    # The first two are left points, the last two are right points
    left_points = sorted_corners_by_x[:2]
    right_points = sorted_corners_by_x[2:]
    
    # Sort left points by y-coordinate to get top-left and bottom-left
    top_left = min(left_points, key=lambda p: p[1])
    bottom_left = max(left_points, key=lambda p: p[1])
    
    # Sort right points by y-coordinate to get top-right and bottom-right
    top_right = min(right_points, key=lambda p: p[1])
    bottom_right = max(right_points, key=lambda p: p[1])
    
    # Return in anti-clockwise order starting from top-left
    return [top_left, bottom_left, bottom_right, top_right]

def join_lines(lines, direction='vertical', tolerance=1.0, angle_tol=1.0, page=None, has_thickness=False):
    if not lines:
        return []

    # 1. Normalize line directions
    new_lines = []
    already_seen = set()
    for line in lines:
        if has_thickness:
            p1, p2, thickness = line
        else:
            p1, p2 = line
        if direction == 'vertical':
            if p1.y > p2.y:
                p1, p2 = p2, p1
        elif direction == 'horizontal':
            if p1.x > p2.x:
                p1, p2 = p2, p1
        if (p1, p2) in already_seen:
            continue
        already_seen.add((p1, p2))
        if has_thickness:
            new_lines.append((Point(p1.x, p1.y), Point(p2.x, p2.y), thickness))
        else:
            new_lines.append((Point(p1.x, p1.y), Point(p2.x, p2.y)))
    lines = new_lines

    iteration = 0
    while True:
        iteration += 1
        print(f"Join lines {direction} iteration {iteration}")
        # 2. Sort lines to group collinear lines together
        if direction == 'vertical':
            lines.sort(key=lambda line: ((line[0].x + line[1].x)/2, line[0].y))
        else: # horizontal
            lines.sort(key=lambda line: ((line[0].y + line[1].y)/2, line[0].x))

        new_lines = []
        already_merged = set()
        for i in range(len(lines)):
            if i in already_merged:
                continue
            line1 = lines[i]
            merged = False
            for j in range(i+1, len(lines)):
                if j == len(lines):
                    break
                if j in already_merged:
                    continue
                line2 = lines[j]

                if has_thickness:
                    cp1, cp2, thickness1 = line1
                    np1, np2, thickness2 = line2
                else:
                    cp1, cp2 = line1
                    np1, np2 = line2

                cp_angle = np.degrees(np.arctan2(cp2.y - cp1.y, cp2.x - cp1.x))
                np_angle = np.degrees(np.arctan2(np2.y - np1.y, np2.x - np1.x))

                if abs(cp_angle - np_angle) > angle_tol:
                    continue

                intersection, reason = get_line_intersection_parallel((cp1, cp2), (np1, np2), direction, tolerance)
                if intersection is None:
                    continue

                if direction == 'vertical':
                    # Merge lines by extending the current line to the furthest point
                    if np1.y < cp1.y:
                        new_p1 = np1
                    else:
                        new_p1 = cp1
                    if cp2.y > np2.y:
                        new_p2 = cp2
                    else:
                        new_p2 = np2
                    # sort points
                    if new_p1.y > new_p2.y:
                        new_p1, new_p2 = new_p2, new_p1
                else: # horizontal
                    # Merge lines by extending the current line to the furthest point
                    if np1.x < cp1.x:
                        new_p1 = np1
                    else:
                        new_p1 = cp1
                    if cp2.x > np2.x:
                        new_p2 = cp2
                    else:
                        new_p2 = np2
                    # sort points
                    if new_p1.x > new_p2.x:
                        new_p1, new_p2 = new_p2, new_p1
                if has_thickness:
                    new_thickness = sum([thickness1, thickness2]) / 2.0
                    new_lines.append((new_p1, new_p2, new_thickness))
                else:
                    new_lines.append((new_p1, new_p2))
                merged = True
                already_merged.add(i)
                already_merged.add(j)
                break

            if not merged:
                new_lines.append(line1)

        if len(new_lines) == len(lines):
            break
        lines = new_lines

    return lines


def get_corners_from_drawings(page, drawings, join_tol=2.0, join_angle_tol=1.0):
    """
    Processes drawings to find and plot the four corner points of the graticule.
    """
    horizontal_lines = []
    vertical_lines = []
    
    # Tolerance for categorization
    angle_tol = 1.0
    
    for drawing in drawings:
        for item in drawing['items']:
            if item[0] == 'l':  # Line
                p1, p2 = item[1], item[2]
                angle = np.degrees(np.arctan2(p2.y - p1.y, p2.x - p1.x))
                angle = abs(angle)
                if angle > 90:
                    angle = 180 - angle
                is_horizontal = angle < angle_tol
                is_vertical = abs(angle - 90) < angle_tol
                if is_horizontal:
                    horizontal_lines.append((p1, p2))
                elif is_vertical:
                    vertical_lines.append((p1, p2))

    return get_corners_from_lines(page, vertical_lines, horizontal_lines, line_scale=2, join_tol=join_tol, join_angle_tol=join_angle_tol)

def get_angle(p1, p2, p3):
    """Calculates the angle at point p2 between p1 and p3."""
    v21 = (p1[0] - p2[0], p1[1] - p2[1])
    v23 = (p3[0] - p2[0], p3[1] - p2[1])
    
    dot_product = v21[0] * v23[0] + v21[1] * v23[1]
    
    mag_v21 = np.sqrt(v21[0]**2 + v21[1]**2)
    mag_v23 = np.sqrt(v23[0]**2 + v23[1]**2)
    
    if mag_v21 == 0 or mag_v23 == 0:
        return 0 # Or handle as an error

    cosine_angle = dot_product / (mag_v21 * mag_v23)
    
    # Clamp the value to the valid range for arccos to avoid floating point errors
    cosine_angle = np.clip(cosine_angle, -1.0, 1.0)
    
    angle = np.arccos(cosine_angle)
    
    return np.degrees(angle)

def check_is_rectangle(corners, tolerance_degrees=1.0):
    """
    Checks if the four corners form a rectangle.
    
    Args:
        corners: A list of four points in order [top_left, bottom_left, bottom_right, top_right].
        tolerance_degrees: The allowed deviation from 90 degrees for each angle.
        
    Returns:
        True if the corners form a rectangle within the given tolerance, False otherwise.
    """
    if len(corners) != 4:
        return False
        
    p1, p2, p3, p4 = corners # top_left, bottom_left, bottom_right, top_right
    
    angle1 = get_angle(p4, p1, p2)
    angle2 = get_angle(p1, p2, p3)
    angle3 = get_angle(p2, p3, p4)
    angle4 = get_angle(p3, p4, p1)
    
    angles = [angle1, angle2, angle3, angle4]
    print(f"Calculated angles: {angles}")
    
    for angle in angles:
        if not (90 - tolerance_degrees <= angle <= 90 + tolerance_degrees):
            return False
            
    return True

def has_blue_lines(doc, layer_name, color_tol):
    page = doc[0]
    page_rect = page.rect
    h, w = page_rect.height, page_rect.width
    diag_len = np.sqrt(h*h + w*w)
    drawings = page.get_drawings("rawdict")
    blue_lines = []
    
    for drawing in drawings:
        if drawing.get('layer') != layer_name:
            continue
        color = drawing.get('color')
        if color is not None and is_color_match(color, (0.0, 0.0, 1.0), tol=color_tol):
            for item in drawing['items']:
                if item[0] == 'l':  # Line
                    p1, p2 = item[1], item[2]
                    dist = np.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)
                    blue_lines.append(dist/diag_len)
    big_blue_lines = [ d for d in blue_lines if d > 0.3 ]
    if len(big_blue_lines) > 10:
        print(f"Found {len(big_blue_lines)} big blue lines")
        return True

    return False

def locate_other_layer_name(doc, check_for_blue_lines=False, blue_color_tol=None):
    layer_configs = doc.layer_ui_configs()
    other_layer_numbers = []
    other_layer_names = []
    for config in layer_configs:
        name = config.get('text', '')
        if name.startswith(OTHER_LAYER_NAME_PREFIX):
            other_layer_numbers.append(config.get('number'))
            other_layer_names.append(name)
    pprint(f"Found {len(other_layer_numbers)} layers starting with {OTHER_LAYER_NAME_PREFIX}")
    pprint(other_layer_names)

    for i,num in enumerate(other_layer_numbers):
        print(f"Checking Other layer: number {num}, name {other_layer_names[i]}")
        # switch on the layer
        doc.set_layer_ui_config(num, action=0)
        text = doc[0].get_text("text")
        print(f"Extracted text length: {len(text)}")
        if text.find('COPYRIGHT') >= 0:
            print(f"Located 'COPYRIGHT' text in layer {other_layer_names[i]}")
            if check_for_blue_lines and not has_blue_lines(doc, other_layer_names[i], blue_color_tol):
                print(f"Layer {other_layer_names[i]} does not has blue lines, skipping it")
                continue
            return other_layer_names[i]
    
    return None


def rename_layers(doc):

    layer_configs = doc.layer_ui_configs()
    
    if not layer_configs:
        print("No layers with UI configurations found. No layers will be renamed.")
        return

    ocgs = doc.get_ocgs()
    name_to_xref = {props.get('name'): xref for xref, props in ocgs.items() if props}

    for i, config in enumerate(layer_configs):
        old_name = config.get('text', '')
        ocg_xref = name_to_xref.get(old_name)

        if not ocg_xref:
            continue

        #print(f"Layer {i+1}: xref {ocg_xref}, old name: {old_name}")
        
        if old_name.endswith('\udcc0\udc80'):
            new_name = old_name[:-2]
        else:
            new_name = old_name

        # Update the dictionary in place, to match original logic
        doc.xref_set_key(ocg_xref, "Name", f"({new_name})")

        #print(f"Renamed {old_name} → {new_name}")

def is_color_match(c1, c2, tol):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))

def is_long_and_axis_aligned(p1, p2, page_rect, angle_tol, min_line_scale):
    x0, y0 = p1.x, p1.y
    x1, y1 = p2.x, p2.y
    w, h = page_rect.width, page_rect.height
    angle = np.degrees(np.arctan2(y1 - y0, x1 - x0))
    length = np.sqrt((x1 - x0)**2 + (y1 - y0)**2)
    # check if eithr horizontal or vertical within angle_tol 
    angle = abs(angle)
    if angle > 90:
        angle = 180 - angle
    is_horizontal = angle < angle_tol
    is_vertical = abs(angle - 90) < angle_tol
    #print(f"Line from {p1} to {p2}, angle {angle:.2f}, length {length:.2f}, is_horizontal {is_horizontal}, is_vertical {is_vertical}")

    if is_horizontal and length >= w / min_line_scale:
        return True, True
    elif is_vertical and length >= h / min_line_scale:
        return True, False
    return False, None


def locate_lines(doc, angle_tol=1, color=(0.0, 0.0, 0.0), color_tol=0.01, min_line_scale=8):
    page = doc[0]
    drawings = page.get_drawings()
    page_rect = page.rect
    h_lines = []
    v_lines = []
    for drawing in drawings:
        stroke_color = drawing.get('color')
        if stroke_color is None:
            continue

        #layer = drawing.get('layer', '')
        #print(f"Drawing stroke color: {stroke_color}, layer: {layer}")
        #for item in drawing['items']:
        #    if item[0] == 'l':
        #        p1, p2 = item[1], item[2]
        #        p1 = (p1.x, p1.y)
        #        p2 = (p2.x, p2.y)
        #        dist = np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
        #        print(dist)

        if not is_color_match(stroke_color, color, color_tol):
            continue
        for item in drawing['items']:
            if item[0] == 'l':
                p1, p2 = item[1], item[2]
                is_long, is_horizontal = is_long_and_axis_aligned(p1, p2, page_rect, angle_tol, min_line_scale)
                if is_long:
                    thickness = drawing.get('width', 1.0)
                    if is_horizontal:
                        h_lines.append( (p1, p2, thickness) )
                    if not is_horizontal:
                        v_lines.append( (p1, p2, thickness) )
    return v_lines, h_lines

class SOIProcessor(TopoMapProcessor):

    def __init__(self, filepath, extra, index_box):
        super().__init__(filepath, extra, index_box)
        self.corner_overrides = extra.get('corner_overrides', None)
        self.warp_jpeg_export_quality = 100
        self.blue_color_tol = extra.get('blue_color_tol', 0.5)
        self.black_color_tol = extra.get('black_color_tol', 0.1)
        self.blue_line_scale = extra.get('blue_line_scale', 32)
        self.black_line_scale = extra.get('black_line_scale', 16)
        self.auto_remove_lines = extra.get('auto_remove_lines', True)
        self.lines_to_remove = extra.get('lines_to_remove', None)
        self.lines_to_remove_widths = extra.get('lines_to_remove_widths', None)
        self.remove_lines_using_image_processing = extra.get('remove_lines_using_image_processing', False)
        self.other_layer_name = extra.get('other_layer_name', None)

    def rotate(self):
        workdir = self.get_workdir()
        full_img_path = workdir / 'full.jpg'
        if full_img_path.exists():
            print(f"Full image already exists at {full_img_path}, skipping rotate()")
            return

        pdf_file_path = Path(self.filepath)
        doc = pymupdf.open(self.filepath)
        if doc.page_count != 1:
            raise ValueError(f"Document {self.filepath} has no pages")

        if not self.auto_remove_lines:
            workdir.mkdir(parents=True, exist_ok=True)
            if self.lines_to_remove is None:
                run_external(f'bin/mutool draw -n data/SOI_FONTS -r {DPI} -c rgb -o {str(full_img_path)} {str(pdf_file_path)}')
                return

            pre_img_path = workdir / 'pre_full.jpg'
            run_external(f'bin/mutool draw -n data/SOI_FONTS -r {DPI} -c rgb -o {str(pre_img_path)} {str(pdf_file_path)}')
            black_lines = self.lines_to_remove.get('black', [])
            blue_lines = self.lines_to_remove.get('blue', [])
            blue_line_width = self.lines_to_remove_widths['blue']
            black_line_width = self.lines_to_remove_widths['black']

            img = cv2.imread(str(pre_img_path))
            w = img.shape[1]
            factor = DPI / 72.0
            for i in range(2):
                for color, lines, thickness in [('blue', blue_lines, blue_line_width), ('black', black_lines, black_line_width)]:
                    for line in lines:
                        p1, p2 = line
                        p1, p2 = (Point(p1[0], p1[1]), Point(p2[0], p2[1]))
                        if thickness < 2.0:
                            thickness = 2.0
                        line_buf_ratio = thickness / (w * 2.0)
                        line_removal_params = LineRemovalParams(
                            line_buf_ratio=line_buf_ratio,
                            blur_buf_ratio=line_buf_ratio * 4,
                            blur_kern_ratio=line_buf_ratio * 5,
                            blur_repeat=2
                        )
                        self.remove_line([[p1.x,p1.y], [p2.x,p2.y]], img, line_removal_params)
                        #LineRemovalParams = namedtuple('LineRemovalParams', ['line_buf_ratio', 'blur_buf_ratio', 'blur_kern_ratio', 'blur_repeat'])
            cv2.imwrite(str(full_img_path), img)
            return

        ocgs = doc.get_ocgs()

        # do it before the renaming because we are getting wrong answers afterwards

        has_weird_endings = False
        for ocg in ocgs.values():
            if ocg.get('name', '').endswith('\udcc0\udc80'):
                has_weird_endings = True
                break

        if has_weird_endings:
            print('Renaming layers to remove weird endings')
            rename_layers(doc)
            workdir.mkdir(parents=True, exist_ok=True)
            renamed_pdf_path = workdir / 'renamed.pdf'
            pdf_file_path = renamed_pdf_path
            doc.save(str(renamed_pdf_path), garbage=4, deflate=True, clean=True)
            doc = pymupdf.open(renamed_pdf_path)
            ocgs = doc.get_ocgs()


        graticule_xref = None
        other2_xref = None

        for prefix in GRATICULE_LAYER_NAME_PREFIXES:
            for xref, props in ocgs.items():
                if props.get('name', '').startswith(prefix):
                    graticule_xref = xref
                    break
            if graticule_xref is not None:
                break

        if self.other_layer_name is not None:
            other_layer_name = self.other_layer_name
        else:
            other_layer_name = locate_other_layer_name(doc, check_for_blue_lines=True, blue_color_tol=self.blue_color_tol)
        if other_layer_name is not None:
            for xref, props in ocgs.items():
                print(f"Checking layer name: {props.get('name', '')}")
                if props.get('name', '').replace('\udcc0\udc80', '') == other_layer_name:
                    other2_xref = xref
                    break

        if graticule_xref is None or other2_xref is None or self.remove_lines_using_image_processing:
            print(f"One or both specified layers not found in the PDF. {GRATICULE_LAYER_NAME_PREFIXES} xref: {graticule_xref}, {OTHER_LAYER_NAME_PREFIX} xref: {other2_xref}")

            pre_img_path = workdir / 'pre_full.jpg'
            workdir.mkdir(parents=True, exist_ok=True)
            run_external(f'bin/mutool draw -n data/SOI_FONTS -r {DPI} -c rgb -o {str(pre_img_path)} {str(pdf_file_path)}')

            # we will locate the graticule lines and remove them using image processing instead
            black_v_lines, black_h_lines = locate_lines(doc, angle_tol=1, color=(0.0, 0.0, 0.0), color_tol=self.black_color_tol, min_line_scale=self.black_line_scale)
            black_lines = black_v_lines + black_h_lines
            to_disp = [ (li[0], li[1]) for li in black_lines ]
            display_lines([], to_disp, title="Black Lines")
            pprint(f"Removing {len(black_lines)} black lines")

            print(f"Using blue color tolerance of {self.blue_color_tol}")
            blue_v_lines, blue_h_lines = locate_lines(doc, angle_tol=2, color=(0.0, 0.0, 1.0), color_tol=self.blue_color_tol, min_line_scale=self.blue_line_scale)
            blue_lines = blue_v_lines + blue_h_lines
            to_disp = [ (li[0], li[1]) for li in blue_lines ]
            #display_lines([], to_disp, title="Black Lines")
            pprint(f"Removing {len(blue_lines)} blue lines")

            if len(black_lines) < 4 or len(blue_lines) < 24:
                raise ValueError(f"Could not find enough lines to remove graticule, black lines {len(black_lines)}, blue lines {len(blue_lines)}")

            img = cv2.imread(str(pre_img_path))
            w = img.shape[1]
            factor = DPI / 72.0
            for i in range(2):
                for color, lines in [('blue', blue_lines), ('black', black_lines)]:
                    for line in lines:
                        p1, p2, thickness = line
                        p1 = Point(p1.x*factor, p1.y*factor)
                        p2 = Point(p2.x*factor, p2.y*factor)
                        thickness = thickness * factor
                        if thickness < 2.0:
                            thickness = 2.0
                        line_buf_ratio = thickness / (w * 2.0)
                        line_removal_params = LineRemovalParams(
                            line_buf_ratio=line_buf_ratio,
                            blur_buf_ratio=line_buf_ratio * 4,
                            blur_kern_ratio=line_buf_ratio * 5,
                            blur_repeat=2
                        )
                        self.remove_line([[p1.x,p1.y], [p2.x,p2.y]], img, line_removal_params)
                        #LineRemovalParams = namedtuple('LineRemovalParams', ['line_buf_ratio', 'blur_buf_ratio', 'blur_kern_ratio', 'blur_repeat'])
            cv2.imwrite(str(full_img_path), img)
        else:
            layers_to_turn_off = [ graticule_xref, other2_xref ]

            # Use doc.set_ocg_state directly
            # state=0 means off, state=1 means on

            all_ocg_xrefs = list(ocgs.keys())
            remaining_xrefs = [oxref for oxref in all_ocg_xrefs if oxref not in layers_to_turn_off]
            print(f"Turning off layers: {', '.join([doc.get_ocgs()[xref]['name'] for xref in layers_to_turn_off])}")
            print(f"Keeping on layers: {', '.join([doc.get_ocgs()[xref]['name'] for xref in remaining_xrefs])}")
            doc.set_layer(config=-1, on=remaining_xrefs, off=layers_to_turn_off)

            workdir.mkdir(parents=True, exist_ok=True)
            temp_pdf_path = workdir / 'graticule_removed.pdf'
            doc.save(str(temp_pdf_path), garbage=4, deflate=True, clean=True)

            run_external(f'bin/mutool draw -n data/SOI_FONTS -r {DPI} -c rgb -o {str(full_img_path)} {str(temp_pdf_path)}')
        #temp_pdf_path.unlink()

    def get_crs_proj(self):
        return 'EPSG:4326'

    def get_original_pixel_coordinate(self, c):
        return c

    def get_resolution(self):
        return 'auto'

    def get_corners(self):

        if self.mapbox_corners is not None:
            return self.mapbox_corners

        if self.corner_overrides is not None:
            self.mapbox_corners = self.corner_overrides
            return self.corner_overrides

        workdir = self.get_workdir()
        corners_file = workdir.joinpath('corners.json')
        if corners_file.exists():
            with open(corners_file, 'r') as f:
                corners = json.load(f)

            self.mapbox_corners = corners
            return corners

        renamed_pdf_path = workdir / 'renamed.pdf'
        if renamed_pdf_path.exists():
            doc = pymupdf.open(renamed_pdf_path)
        else:
            doc = pymupdf.open(self.filepath)

        page = doc[0]

        graticule_drawings = []
        #graticule_layer_prefix_picked = None
        for drawing in page.get_drawings("rawdict"):
            layer = drawing.get('layer')
            if layer is None:
                continue
            is_graticule_layer = False
            for prefix in GRATICULE_LAYER_NAME_PREFIXES:
                if layer.startswith(prefix):
                    is_graticule_layer = True
                    #graticule_layer_prefix_picked = prefix
                    break
            if not is_graticule_layer:
                continue

            #if not is_color_match(drawing.get('color', (0,0,0)), (0.0, 0.0, 0.0), BLACK_COLOR_TOL):
            #    continue

            graticule_drawings.append(drawing)
        pprint(f"Found {len(graticule_drawings)} graticule drawings")
        #pprint(graticule_drawings)
        corners = None
        if len(graticule_drawings) > 0:
            print("Using graticule layer for corner detection")
            corners = get_corners_from_drawings(page, graticule_drawings, join_tol=1.0, join_angle_tol=1.0)

        if corners is None or len(corners) != 4:
            print(f"No graticule layers found in {self.filepath}, trying an alternate approach")
            v_lines, h_lines = locate_lines(doc, angle_tol=1, color=(0.0, 0.0, 0.0), color_tol=0.5, min_line_scale=1000)
            pprint(f"Located {len(v_lines)} vertical and {len(h_lines)} horizontal lines")
            if len(v_lines) < 2 or len(h_lines) < 2:
                raise ValueError(f"Could not find enough graticule lines in {self.filepath}")
            v_lines = [ (li[0], li[1]) for li in v_lines ]
            h_lines = [ (li[0], li[1]) for li in h_lines ]
            corners = get_corners_from_lines(page, v_lines, h_lines, line_scale=2, join_tol=1.0, join_angle_tol=1.0)

        if corners is None:
            raise ValueError(f"Could not determine corners for {self.filepath}")

        if not check_is_rectangle(corners):
            raise ValueError(f"The calculated corners do not form a rectangle for {self.filepath}")

        zoom_factor = DPI / 72.0
        corners = [ (x * zoom_factor, y * zoom_factor) for (x, y) in corners ]

        self.mapbox_corners = corners
        self.ensure_dir(workdir)
        with open(corners_file, 'w') as f:
            json.dump(corners, f, indent = 4)

        return corners

 
def get_sheetmap():
    sheetmap_file = Path('data/index_25k.geojson')
    data = json.loads(sheetmap_file.read_text())
    features = data['features']
    sheetmap_file = Path('data/extra.geojson')
    data = json.loads(sheetmap_file.read_text())
    features += data['features']
    sheet_map = {}
    for feature in features:
        props = feature['properties']
        id = props['id']
        geom = feature['geometry']
        if geom['type'] == 'Polygon':
            coords = geom['coordinates'][0]
        elif geom['type'] == 'MultiPolygon':
            coords = geom['coordinates'][0][0]
        sheet_map[id] = coords
    return sheet_map

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

    print(f"Found {len(image_files)} pdf files")

    special_cases_file = Path(__file__).parent / 'special_cases.json'

    special_cases = {}
    if special_cases_file.exists():
        special_cases = json.loads(special_cases_file.read_text())

    sheet_map = get_sheetmap()

    bad_files = Path('bad_files.txt').read_text().split('\n')
    bad_files = set([ f.strip() for f in bad_files if f.strip() != '' ])

    total = len(image_files)
    processed_count = 0
    failed_count = 0
    success_count = 0
    # Process each file
    for filepath in image_files:
        print(f'==========  Processed: {processed_count}/{total} Success: {success_count} Failed: {failed_count} processing {filepath.name} ==========')
        extra = special_cases.get(filepath.name, {})
        id = filepath.name.replace('.pdf', '')
        if filepath.name in bad_files:
            print(f"Skipping known bad file {filepath.name}")
            continue

        try:
            processor = SOIProcessor(filepath, extra, sheet_map[id])
            processor.process()
            success_count += 1
        except Exception as ex:
            print(f'parsing {filepath} failed with exception: {ex}')
            failed_count += 1
            traceback.print_exc()
            raise
            processor.prompt()
        processed_count += 1

    print(f"Processed {processed_count} images, failed_count {failed_count}, success_count {success_count}")



if __name__ == "__main__":
    import os
    os.environ['GDAL_PAM_ENABLED'] = 'NO'
    process_files()
 
