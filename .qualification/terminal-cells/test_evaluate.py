import copy,json,unittest
from evaluate import PKG,NEW,ROOTS,parse,list_tests,compare,validate_timestamps
OTHER='example.local/other';EMPTY='example.local/no-tests';INVENTORY={PKG,OTHER,EMPTY}

def listed(fixed=False):
 roots={PKG+'::TestOriginal',OTHER+'::TestExistingSkip'}|(ROOTS if fixed else set())
 out=[]
 for p in sorted(INVENTORY):
  out.append({'Action':'start','Package':p})
  for key in sorted(roots):
   if key.startswith(p+'::'):out.append({'Action':'output','Package':p,'Output':key.split('::',1)[1]+'\n'})
  if p==EMPTY:out.append({'Action':'output','Package':p,'Output':'?\t'+p+'\t[no test files]\n'})
  out.append({'Action':'skip' if p==EMPTY else 'pass','Package':p})
 return out

def outcomes(fixed=False):
 cases={PKG+'::TestOriginal':('pass',''),OTHER+'::TestExistingSkip':('skip','    fixture.go:7: external tool unavailable\n')}
 cases.update({k:('pass','') if fixed else v for k,v in NEW.items()});out=[]
 for p in sorted(INVENTORY):out.append({'Action':'start','Package':p})
 for key,(a,reason) in sorted(cases.items()):
  p,t=key.split('::',1);out.append({'Action':'run','Package':p,'Test':t})
  if reason:out.append({'Action':'output','Package':p,'Test':t,'Output':reason})
  out.append({'Action':a,'Package':p,'Test':t})
 for p in sorted(INVENTORY):
  if p==EMPTY:out.append({'Action':'output','Package':p,'Output':'?\t'+p+'\t[no test files]\n'})
  out.append({'Action':'skip' if p==EMPTY else 'fail' if p==PKG and not fixed else 'pass','Package':p})
 return out

def raw(data):return '\n'.join(json.dumps(e) for e in data)
class EvaluatorControls(unittest.TestCase):
 def setUp(self):self.data=[outcomes(),outcomes(True),listed(),listed(True)]
 def run_compare(self):return compare(parse(raw(self.data[0]),INVENTORY),parse(raw(self.data[1]),INVENTORY),list_tests(raw(self.data[2]),INVENTORY),list_tests(raw(self.data[3]),INVENTORY),True)
 def reject(self,index,mutation):
  mutation(self.data[index])
  with self.assertRaises((ValueError,KeyError)):self.run_compare()
 def test_valid_exact_original_and_new(self):self.assertEqual(self.run_compare()['newExpectedBaseline'],{'fail':11,'pass':5})
 def test_unrelated_package_failure(self):self.reject(0,lambda es:next(e for e in es if e.get('Package')==OTHER and not e.get('Test') and e['Action']=='pass').update(Action='fail'))
 def test_missing_identity(self):self.reject(0,lambda es:es.__setitem__(slice(None),[e for e in es if e.get('Test')!='TestOriginal']))
 def test_duplicate_start(self):self.reject(0,lambda es:es.append(copy.deepcopy(next(e for e in es if e['Action']=='run'))))
 def test_duplicate_outcome(self):self.reject(0,lambda es:es.append(copy.deepcopy(next(e for e in es if e.get('Test') and e['Action']=='fail'))))
 def test_duplicate_package_outcome(self):self.reject(0,lambda es:es.append(copy.deepcopy(es[-1])))
 def test_fixed_failure(self):self.reject(1,lambda es:next(e for e in es if e.get('Test')=='TestOriginal' and e['Action']=='pass').update(Action='fail'))
 def test_wrong_new_failure(self):self.reject(0,lambda es:next(e for e in es if e.get('Test')=='TestTraceViewCJKRowsStayWithinTerminal' and e['Action']=='fail').update(Action='pass'))
 def test_new_skip(self):self.reject(1,lambda es:next(e for e in es if e.get('Test')=='TestTraceViewCJKRowsStayWithinTerminal' and e['Action']=='pass').update(Action='skip'))
 def test_changed_original_skip_reason(self):self.reject(0,lambda es:next(e for e in es if e.get('Test')=='TestExistingSkip' and e['Action']=='output').update(Output='different reason\n'))
 def test_same_omitted_listed_method(self):
  for i in [0,1]:self.data[i]=[e for e in self.data[i] if e.get('Test')!='TestOriginal']
  with self.assertRaises(ValueError):self.run_compare()
 def test_missing_package(self):self.reject(0,lambda es:es.pop())
 def test_build_fail(self):self.reject(0,lambda es:es.append({'Action':'build-fail','ImportPath':PKG}))
 def test_changed_list_inventory(self):self.reject(2,lambda es:es.append({'Action':'output','Package':PKG,'Output':'TestUnexpected\n'}))
 def test_list_duplicate_method(self):self.reject(2,lambda es:es.append({'Action':'output','Package':PKG,'Output':'TestOriginal\n'}))
 def test_missing_outcome(self):self.reject(0,lambda es:es.remove(next(e for e in es if e.get('Test')=='TestOriginal' and e['Action']=='pass')))
 def test_timestamps_aware_ordered(self):validate_timestamps('2026-10-13T09:00:00+01:00','2026-10-13T08:00:00+00:00')
 def test_timestamps_reversed(self):
  with self.assertRaises(ValueError):validate_timestamps('2026-10-13T08:00:01+00:00','2026-10-13T09:00:00+01:00')
 def test_timestamps_malformed(self):
  with self.assertRaises(ValueError):validate_timestamps('not-a-date','2026-10-13T08:00:00+00:00')
 def test_timestamps_naive(self):
  with self.assertRaises(ValueError):validate_timestamps('2026-10-13T08:00:00','2026-10-13T08:00:00+00:00')
if __name__=='__main__':unittest.main()
