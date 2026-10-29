import unittest,tempfile
from pathlib import Path
from core import Radar,parse_csv,THRESHOLD
from common import ROOT
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Radar(Path(self.tmp.name)/'test.db')
    def test_holdout_separate_and_metrics(self):
        e=self.r.evaluate();self.assertEqual(e['test_count'],28);self.assertEqual(len(e['confusion_matrix']),4);self.assertGreater(e['classification']['macro avg']['f1-score'],.5)
    def test_unknown_text_abstains(self): self.assertEqual(self.r.classify('zxqv 9481 yuiop')['topic'],'проверить вручную')
    def test_csv_validation(self):
        for text in ['text\nhello','review_id,text,rating,date\n1,abc,9,2026-10-01','review_id,text,rating,date\n1,abc,2,bad']:
            with self.assertRaises(ValueError): parse_csv(text)
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError): parse_csv('review_id,text,rating,date\n1,abc,1,2026-10-01\n1,xyz,2,2026-10-01')
    def test_dedup_and_positive_exclusion(self):
        row={'review_id':'1','text':'Деньги списали дважды','rating':1,'date':'2026-10-01'}
        result=self.r.analyze([row,dict(row,review_id='2'),dict(row,review_id='3',text='Спасибо за помощь',rating=5)])
        self.assertEqual(result['total'],2);self.assertEqual(result['duplicates_removed'],1);self.assertEqual(sum(x['count'] for x in result['backlog']),1)
    def test_correction_bound_to_text(self):
        row={'review_id':'1','text':'Не могу найти товар','rating':1,'date':'2026-10-01'}
        self.r.correct('1',row['text'],'оплата');self.assertTrue(self.r.analyze([row])['rows'][0]['corrected'])
        self.assertFalse(self.r.analyze([dict(row,text='Другой текст')])['rows'][0]['corrected'])
    def test_priority_formula(self):
        rows=parse_csv((ROOT/'data/reviews.csv').read_text());r=self.r.analyze(rows)
        for b in r['backlog']:self.assertAlmostEqual(b['score'],round(100*b['count']/r['total']*b['severity']/5,2))
if __name__=='__main__':unittest.main()
