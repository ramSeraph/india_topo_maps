# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pillow",
#     "surya-ocr",
# ]
# ///

import json
from pathlib import Path
from PIL import Image
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
import argparse

def main():
    parser = argparse.ArgumentParser(description="Run Surya OCR on a list of images.")
    parser.add_argument("files", nargs="+", help="List of image files to process.")
    args = parser.parse_args()

    foundation_predictor = FoundationPredictor()
    recognition_predictor = RecognitionPredictor(foundation_predictor)
    detection_predictor = DetectionPredictor()
    recognition_predictor.batch_size = 8

    txt_dir = Path('text')
    txt_dir.mkdir(exist_ok=True)

    for p_str in args.files:
        p = Path(p_str)
        print(f'Processing {p.name} on GPU {args.gpu}...')
        txt_file = txt_dir / f'{p.stem}.json'
        if txt_file.exists():
            print(f'Skipping {p.name}, already processed.')
            continue
        image = Image.open(p)

        predictions = recognition_predictor([image], det_predictor=detection_predictor)
        prediction = predictions[0]
        textlines = prediction.text_lines
        all_texts = []
        for textline in textlines:
            item = { 'text': textline.text, 'confidence': textline.confidence, 'polygon': textline.polygon }
            all_texts.append(item)

        with open(txt_file, 'w') as f:
            json.dump(all_texts, f, indent=4)

if __name__ == "__main__":
    main()
