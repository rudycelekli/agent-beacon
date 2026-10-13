import copy
import json
from pathlib import Path
import tempfile
import unittest
from compare import compare, EXPECTED

P=next(iter(EXPECTED)).split('::')[0]
OTHER='github.com/asymptote-labs/agent-beacon/cli/beacon/internal/positive'

def receipt(outcome):
    rows=[]
    for name in sorted(EXPECTED):
        test=name.split('::')[1]
        rows += [{'Action':'run','Package':P,'Test':test},{'Action':outcome,'Package':P,'Test':test}]
    rows += [{'Action':outcome,'Package':P}, {'Action':'run','Package':OTHER,'Test':'TestPositive'},
             {'Action':'pass','Package':OTHER,'Test':'TestPositive'}, {'Action':'pass','Package':OTHER}]
    return rows

class ComparatorControls(unittest.TestCase):
    def setUp(self):self.base,self.fixed=receipt('fail'),receipt('pass')
    def run_compare(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[]
            for name,rows in [('base',self.base),('fixed',self.fixed)]:
                p=Path(d)/name;p.write_text(''.join(json.dumps(r)+'\n' for r in rows));paths.append(p)
            return compare(*paths)
    def reject(self):
        with self.assertRaises(RuntimeError):self.run_compare()
    def test_exact_two_regressions(self):self.assertEqual(len(self.run_compare()['only_changed_tests']),2)
    def test_same_unrelated_package_failure(self):self.base[-1]['Action']=self.fixed[-1]['Action']='fail';self.reject()
    def test_fixed_package_failure(self):self.fixed[-1]['Action']='fail';self.reject()
    def test_unexpected_baseline_case_failure(self):self.base[-2]['Action']='fail';self.reject()
    def test_one_negative_missing(self):self.base[1]['Action']='pass';self.reject()
    def test_fixed_regression_fail(self):self.fixed[1]['Action']='fail';self.reject()
    def test_lost_case(self):self.fixed=self.fixed[2:];self.reject()
    def test_duplicate_outcome(self):self.fixed.append(copy.deepcopy(self.fixed[1]));self.reject()
    def test_build_fail(self):self.fixed.append({'Action':'build-fail'});self.reject()
    def test_missing_case_outcome(self):self.fixed.pop(1);self.reject()
    def add_skip(self):
        rows=[{'Action':'run','Package':OTHER,'Test':'TestSkip'},{'Action':'output','Package':OTHER,'Test':'TestSkip','Output':'existing reason'},{'Action':'skip','Package':OTHER,'Test':'TestSkip'}]
        self.base+=copy.deepcopy(rows);self.fixed+=copy.deepcopy(rows)
    def test_existing_skip(self):self.add_skip();self.assertEqual(self.run_compare()['preserved_skips'],1)
    def test_changed_skip_reason(self):self.add_skip();self.fixed[-2]['Output']='changed';self.reject()
    def test_new_skip(self):self.fixed.insert(-2,{'Action':'output','Package':OTHER,'Test':'TestPositive','Output':'new reason'});self.fixed[-2]['Action']='skip';self.reject()

if __name__=='__main__':unittest.main()
