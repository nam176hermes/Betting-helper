import unittest
from request_budget import estimate, batch_ids
class BudgetTests(unittest.TestCase):
    def test_constant(self):
        b=estimate([(7200,15)])
        self.assertEqual((b.periodic,b.calls,b.with_reserve),(480,485,582))
    def test_30_seconds(self): self.assertEqual(estimate([(7200,30)]).calls,245)
    def test_concurrent(self):
        for n in (1,3,5):
            self.assertEqual(len(batch_ids(list(range(1,n+1)))),1)
            self.assertEqual(estimate([(7200,15)]).calls,485)
    def test_sequential(self): self.assertEqual(sum(estimate([(7200,15)]).calls for _ in range(5)),2425)
    def test_adaptive_125min(self): self.assertEqual(estimate([(600,60),(6000,15),(900,60)]).calls,430)
    def test_fallback(self): self.assertEqual(estimate([(7200,15)],fallback_calls=5*120).calls,1085)
    def test_half_open(self): self.assertEqual(estimate([(15,15)],setup=0,confirmations=0).periodic,1)
    def test_sorted_dedup(self): self.assertEqual(batch_ids([3,1,3,2]),[(1,2,3)])
    def test_21_split(self): self.assertEqual([len(x) for x in batch_ids(list(range(1,22)))],[20,1])
    def test_empty(self): self.assertEqual(batch_ids([]),[])
    def test_invalid_id(self):
        for ids in ([True],[0],[-1],[1.5]):
            with self.assertRaises(ValueError): batch_ids(ids)
    def test_invalid_interval(self):
        for segs in ([(-1,15)],[(1,0)],[(True,15)]):
            with self.assertRaises(ValueError): estimate(segs)
    def test_invalid_reserve(self):
        for r in ('NaN','Infinity','-0.1','1.1'):
            with self.assertRaises(ValueError): estimate([(1,1)],reserve=r)
if __name__=='__main__': unittest.main()
