"""检查资料的字段、记录身份及公开的参考关系。"""
from pathlib import Path
import json
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'data' / 'records.json'
FIELDS = {'cars': ('id', 'series', 'build'), 'runs': ('id', 'car', 'road', 'phase', 'mode', 'temp', 'speed', 'duration', 'started'), 'notes': ('id', 'observer', 'run_hint', 'text'), 'claims': ('id', 'scope', 'type', 'required', 'evidence'), 'signoffs': ('id', 'claim', 'author', 'text'), 'copy': ('id', 'state', 'refs', 'text')}
RELATIONS = (('runs', 'car', 'cars'), ('notes', 'run_hint', 'runs'), ('signoffs', 'claim', 'claims'), ('copy', 'refs', 'signoffs'))


class InputFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = json.loads(SOURCE.read_text(encoding='utf-8'))

    def test_tables_follow_their_declared_fields(self):
        self.assertEqual(set(self.tables), set(FIELDS))
        for table, fields in FIELDS.items():
            with self.subTest(table=table):
                self.assertTrue(self.tables[table], table)
                for row in self.tables[table]:
                    self.assertEqual(set(row), set(fields))

    def test_records_can_be_referenced_without_collisions(self):
        for table, rows in self.tables.items():
            with self.subTest(table=table):
                key = 'id' if 'id' in FIELDS[table] else 'seq'
                identities = [row[key] for row in rows]
                self.assertEqual(len(identities), len(set(identities)))
                self.assertTrue(all(isinstance(value, (int, str)) and value for value in identities))

    def test_reference_values_exist(self):
        for table, field, target_table in RELATIONS:
            with self.subTest(table=table, field=field):
                target_ids = {row['id'] for row in self.tables[target_table]}
                for row in self.tables[table]:
                    value = row[field]
                    if value is None:
                        continue
                    references = value if isinstance(value, list) else [value]
                    self.assertTrue(set(references) <= target_ids, row)
