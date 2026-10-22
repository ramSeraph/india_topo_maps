import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


spec = importlib.util.spec_from_file_location('compress', Path(__file__).with_name('compress.py'))
compress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compress)


class DpiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        inter_dir = patch.object(compress, 'inter_dir', self.root / 'inter')
        inter_dir.start()
        self.addCleanup(inter_dir.stop)
        self.converter = compress.Converter('sheet.pdf')

    def test_dpi_update_preserves_jpeg_scan_and_normalizes_both_metadata_formats(self):
        for dpi in (None, (72, 96), (300, 300)):
            with self.subTest(dpi=dpi):
                # Spaces also exercise passing the path as a single argument.
                file = self.root / 'sheet with spaces.jpg'
                exif = Image.Exif()
                exif[282] = 144
                exif[283] = 144
                exif[296] = 2
                image = Image.new('RGB', (32, 24), (10, 100, 200))
                image.save(file, exif=exif, **({'dpi': dpi} if dpi else {}))
                before = file.read_bytes()
                scan = before[before.index(b'\xff\xda'):]

                self.converter.fix_dpi(file)

                after = file.read_bytes()
                self.assertEqual(after[after.index(b'\xff\xda'):], scan)
                with Image.open(file) as updated:
                    self.assertEqual(updated.size, (32, 24))
                    self.assertEqual(updated.info['dpi'], (300, 300))
                    self.assertEqual(updated.getexif()[282], 300)
                    self.assertEqual(updated.getexif()[283], 300)
                    self.assertEqual(updated.getexif()[296], 2)
                self.assertFalse(Path(f'{file}_original').exists())

    def test_dpi_update_is_repeatable_on_cached_image(self):
        file = self.root / 'cached.jpg'
        Image.new('RGB', (32, 24)).save(file)
        self.converter.fix_dpi(file)
        before = file.read_bytes()

        self.converter.fix_dpi(file)

        self.assertEqual(file.read_bytes(), before)

    def test_metadata_failure_stops_processing_without_changing_file(self):
        file = self.root / 'broken.jpg'
        original = b'not an image'
        file.write_bytes(original)
        with self.assertRaisesRegex(Exception, 'failed with exit code'):
            self.converter.fix_dpi(file)
        self.assertEqual(file.read_bytes(), original)

    def test_small_png_and_cached_png_are_encoded_as_jpeg(self):
        source = self.converter.get_full_img_file()
        cached = self.converter.get_compressed_file()
        Image.new('RGB', (32, 24)).save(source, format='PNG')
        cached.write_bytes(source.read_bytes())
        original = source.read_bytes()
        real_run_external = compress.run_external
        encoded = []

        def encode(cmd):
            if isinstance(cmd, list) and cmd[0] == 'bin/cjpeg':
                encoded.append(cmd)
                with Image.open(cmd[-1]) as image:
                    image.save(cmd[cmd.index('-outfile') + 1], format='JPEG')
            else:
                real_run_external(cmd)

        with patch.object(compress, 'run_external', side_effect=encode):
            self.converter.compress()

        self.assertEqual(len(encoded), 1)
        with Image.open(cached) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.info['dpi'], (300, 300))
        self.assertEqual(source.read_bytes(), original)

    def test_small_jpeg_is_copied_without_reencoding(self):
        source = self.converter.get_full_img_file()
        Image.new('RGB', (32, 24)).save(source, format='JPEG', dpi=(72, 72))
        original = source.read_bytes()

        self.converter.compress()

        output = self.converter.get_compressed_file().read_bytes()
        self.assertEqual(output[output.index(b'\xff\xda'):], original[original.index(b'\xff\xda'):])
        self.assertEqual(source.read_bytes(), original)
        with Image.open(self.converter.get_compressed_file()) as image:
            self.assertEqual(image.info['dpi'], (300, 300))

    def test_last_quality_attempt_can_meet_size_limit(self):
        Image.new('RGB', (32, 24)).save(self.converter.get_full_img_file(), format='PNG')

        def encode(cmd):
            output = Path(cmd[cmd.index('-outfile') + 1])
            quality = int(cmd[cmd.index('-quality') + 1])
            output.write_bytes(b'x' * (500 if quality == 10 else 1500))

        with patch.object(compress, 'MAX_SIZE', 1000), \
                patch.object(compress, 'run_external', side_effect=encode), \
                patch.object(self.converter, 'fix_dpi'):
            self.converter.compress()

        self.assertEqual(self.converter.get_compressed_file().stat().st_size, 500)

    def test_failed_encoding_is_not_reused_as_completed_compression(self):
        Image.new('RGB', (32, 24)).save(self.converter.get_full_img_file(), format='PNG')

        def fail(cmd):
            Path(cmd[cmd.index('-outfile') + 1]).write_bytes(b'partial output')
            raise RuntimeError('encoder interrupted')

        with patch.object(compress, 'run_external', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'encoder interrupted'):
                self.converter.compress()

        self.assertFalse(self.converter.get_compressed_file().exists())
        self.assertFalse((self.converter.file_dir / 'compressed.tmp.jpg').exists())


if __name__ == '__main__':
    unittest.main()
