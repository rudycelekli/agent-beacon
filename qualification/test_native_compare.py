import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_compare import receipt

HERE=Path(__file__).parent
MANIFEST=json.loads((HERE/'manifest.json').read_text())

class NativeComparatorControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for phase in ['baseline','fixed']:
            d=self.root/phase;d.mkdir()
            (d/'result.json').write_text(json.dumps({'status':'PASS','head':MANIFEST['phases'][phase]['head']}))
            for name in ['tracked-before.json','tracked-after.json']:(d/name).write_text('{"source":"hash"}')
            commands=[]
            labels=['cli-build-real-hooks','cli-package-inventory','cli-tests','endpoint-race']
            labels += [name+suffix for name in ['hooks','exporter','observe','sandbox'] for suffix in ['-package-inventory','-tests']]
            for label in labels:
                code=1 if phase=='baseline' and label=='cli-tests' else 0
                commands.append({'label':label,'exit':code,'expected_exit':code})
            (d/'commands.json').write_text(json.dumps(commands))
            for lane in ['cli','hooks','exporter','observe','sandbox']:
                rows=receipt('fail' if phase=='baseline' else 'pass') if lane=='cli' else [
                    {'Action':'run','Package':lane,'Test':'TestOriginal'},
                    {'Action':'pass','Package':lane,'Test':'TestOriginal'},
                    {'Action':'pass','Package':lane}]
                (d/(lane+'-tests.stdout')).write_text(''.join(json.dumps(x)+'\n' for x in rows))
                packages={x['Package'] for x in rows}
                (d/(lane+'-package-inventory.stdout')).write_text('\n'.join(sorted(packages))+'\n')
            (d/'endpoint-race.stdout').write_bytes((d/'hooks-tests.stdout').read_bytes())
    def run_compare(self):
        result=subprocess.run(['python3',str(HERE/'compare_native.py'),str(self.root/'baseline'),str(self.root/'fixed'),str(self.root/'result.json')],capture_output=True,text=True)
        return result.returncode,json.loads((self.root/'result.json').read_text())
    def mutate_json(self,name,fn):
        p=self.root/'fixed'/name;j=json.loads(p.read_text());fn(j);p.write_text(json.dumps(j))
    def test_valid_all_lanes_pass(self):self.assertEqual(self.run_compare()[0],0)
    def test_wrong_head_rejected(self):
        self.mutate_json('result.json',lambda j:j.update(head='0'*40));self.assertNotEqual(self.run_compare()[0],0)
    def test_mutated_source_rejected(self):
        self.mutate_json('tracked-after.json',lambda j:j.update(source='changed'));self.assertNotEqual(self.run_compare()[0],0)
    def test_missing_command_rejected(self):
        self.mutate_json('commands.json',lambda j:j.pop());self.assertNotEqual(self.run_compare()[0],0)
    def test_wrong_exit_rejected(self):
        self.mutate_json('commands.json',lambda j:j[0].update(exit=1));self.assertNotEqual(self.run_compare()[0],0)
    def test_missing_package_receipt_rejected(self):
        p=self.root/'fixed/hooks-package-inventory.stdout';p.write_text('hooks\nlostpackage\n');self.assertNotEqual(self.run_compare()[0],0)
    def test_race_failure_rejected(self):
        p=self.root/'fixed/endpoint-race.stdout';s=p.read_text().replace('"pass"','"fail"');p.write_text(s);self.assertNotEqual(self.run_compare()[0],0)

if __name__=='__main__':unittest.main()
