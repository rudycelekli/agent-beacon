import copy
import json
from pathlib import Path
import tempfile
import unittest
from compare import compare, EXPECTED

P = EXPECTED.split('::')[0]
OTHER='github.com/asymptote-labs/agent-beacon/cli/beacon/internal/positive'

def receipt(mirror):
    return [{'Action':'run','Package':P,'Test':EXPECTED.split('::')[1]},
            {'Action':mirror,'Package':P,'Test':EXPECTED.split('::')[1]},
            {'Action':mirror,'Package':P},
            {'Action':'run','Package':OTHER,'Test':'TestPositive'},
            {'Action':'pass','Package':OTHER,'Test':'TestPositive'},
            {'Action':'pass','Package':OTHER}]

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
    def test_proven_mirror_only_repair(self):self.assertEqual(self.run_compare()['status'],'PASS')
    def test_same_unrelated_package_failure_rejected(self):
        self.base[-1]['Action']=self.fixed[-1]['Action']='fail';self.reject()
    def test_fixed_package_failure_rejected(self):self.fixed[-1]['Action']='fail';self.reject()
    def test_unexpected_baseline_package_failure_rejected(self):self.base[-1]['Action']='fail';self.reject()
    def test_missing_case_outcome_rejected(self):self.fixed.pop(4);self.reject()
    def test_lost_original_identity_rejected(self):self.fixed=self.fixed[:3];self.reject()
    def test_fixed_skip_rejected(self):self.fixed[4]['Action']='skip';self.reject()
    def add_existing_skip(self, reason='environment unavailable'):
        rows=[{'Action':'run','Package':OTHER,'Test':'TestExistingSkip'},
              {'Action':'output','Package':OTHER,'Test':'TestExistingSkip','Output':reason},
              {'Action':'skip','Package':OTHER,'Test':'TestExistingSkip'}]
        self.base.extend(copy.deepcopy(rows));self.fixed.extend(copy.deepcopy(rows))
    def test_existing_skip_preserved(self):
        self.add_existing_skip();self.assertEqual(self.run_compare()['preserved_skips'],1)
    def test_existing_skip_reason_change_rejected(self):
        self.add_existing_skip();self.fixed[-2]['Output']='new reason';self.reject()
    def test_new_skip_with_reason_rejected(self):
        self.fixed.insert(4,{'Action':'output','Package':OTHER,'Test':'TestPositive','Output':'new skip'})
        self.fixed[5]['Action']='skip';self.reject()
    def test_mirror_negative_control_absent(self):self.base=receipt('pass');self.reject()
    def test_native_build_failure_rejected(self):self.fixed.append({'Action':'build-fail'});self.reject()
    def test_duplicate_outcome_rejected(self):self.fixed.append(copy.deepcopy(self.fixed[4]));self.reject()

if __name__=='__main__':unittest.main()
