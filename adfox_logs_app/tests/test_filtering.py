import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from filtering import Rule, filter_log
from operation_state import OperationCancelled

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.tsv.gz'
        self.target = self.root / 'result.tsv'
    def write(self, text):
        with gzip.open(self.source, 'wt') as f: f.write(text)
    def test_named_columns_and_conditions(self):
        self.write('useragent\tflag_virtual\tbanner_id\tcampaign_id\nAndroid\t0\t208684\t99\niOS\t0\t208684\t99\nAndroid\t1\t208684\t99\nAndroid\t0\t99\t208684\nbroken\n')
        result = filter_log(self.source, self.target, [Rule('banner_id','Одно из значений',('208684',)), Rule('flag_virtual','Одно из значений',('0',)), Rule('useragent','Содержит',('Android',))])
        self.assertEqual((result['checked'],result['matched'],result['malformed']), (5,1,1))
    def test_missing_field_preserves_result(self):
        self.write('ip\n127.0.0.1\n')
        self.target.write_text('original')
        with self.assertRaises(ValueError): filter_log(self.source,self.target,[Rule('banner_id','Пусто')])
        self.assertEqual(self.target.read_text(),'original')
    def test_corrupt_archive_preserves_result(self):
        self.write('banner_id\n123\n')
        self.source.write_bytes(self.source.read_bytes()[:-8])
        self.target.write_text('original')
        with self.assertRaises(EOFError): filter_log(self.source,self.target,[Rule('banner_id','Не пусто')])
        self.assertEqual(self.target.read_text(),'original')
        self.assertFalse(list(self.root.glob('*.part')))
    def test_operators(self):
        self.assertFalse(Rule('id','Одно из значений',('01',)).matches('1'))
        self.assertTrue(Rule('ua','Содержит',('Android','iPhone')).matches('x iPhone'))
        self.assertFalse(Rule('ua','Не содержит',('Android','iPhone')).matches('iPhone'))
        self.assertTrue(Rule('ua','Пусто').matches(''))
    def test_plain_no_matches(self):
        source = self.root/'plain.tsv'
        source.write_text('banner_id\n123\n')
        result = filter_log(source,self.target,[Rule('banner_id','Одно из значений',('456',))])
        self.assertEqual(result['matched'],0)
        self.assertEqual(self.target.read_text(),'banner_id\n')

    def test_cancel_removes_temporary_result_and_preserves_old_result(self):
        self.write('banner_id\n208684\n208684\n208684\n')
        self.target.write_text('old result', encoding='utf-8')
        calls = 0

        def checkpoint():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OperationCancelled('stop')

        with self.assertRaises(OperationCancelled):
            filter_log(
                self.source, self.target,
                [Rule('banner_id', 'Одно из значений', ('208684',))],
                checkpoint=checkpoint,
            )
        self.assertEqual(self.target.read_text(encoding='utf-8'), 'old result')
        self.assertFalse(list(self.root.glob('*.part')))

    def test_replace_error_preserves_old_result_and_removes_temporary(self):
        self.write('banner_id\n208684\n')
        self.target.write_text('old result', encoding='utf-8')
        with patch('filtering.os.replace', side_effect=OSError('disk error')):
            with self.assertRaisesRegex(OSError, 'disk error'):
                filter_log(
                    self.source, self.target,
                    [Rule('banner_id', 'Одно из значений', ('208684',))],
                )
        self.assertEqual(self.target.read_text(encoding='utf-8'), 'old result')
        self.assertFalse(list(self.root.glob('*.part')))
