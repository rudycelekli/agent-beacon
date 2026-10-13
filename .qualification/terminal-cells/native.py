"""Native Linux source qualification; no paid sandbox or fake build payload."""
import argparse,datetime,hashlib,json,os,platform,subprocess
from pathlib import Path
from evaluate import parse,list_tests,NEW,ROOTS,PKG
p=argparse.ArgumentParser();p.add_argument('phase',choices=['baseline','fixed']);p.add_argument('source',type=Path);p.add_argument('proof',type=Path);a=p.parse_args()
source=a.source.resolve();proof=a.proof.resolve();proof.mkdir(parents=True,exist_ok=True)
manifest=json.loads(Path(__file__).with_name('manifest.json').read_text());expected=manifest['phases'][a.phase];records=[]
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def command(label,argv,cwd,expected_exit=0,timeout=1800):
 if any(r['label']==label for r in records):raise RuntimeError('duplicate command label')
 start=now();actual=None;error=None
 with (proof/(label+'.stdout')).open('wb') as out,(proof/(label+'.stderr')).open('wb') as err:
  try:actual=subprocess.run(argv,cwd=cwd,stdout=out,stderr=err,timeout=timeout).returncode
  except (subprocess.TimeoutExpired,OSError) as e:error=str(e);err.write(error.encode())
 record={'label':label,'argv':argv,'cwd':str(cwd),'start':start,'end':now(),'actualExit':actual,'expectedExit':expected_exit,'timeoutSeconds':timeout,'error':error,'stdoutSHA256':hashlib.sha256((proof/(label+'.stdout')).read_bytes()).hexdigest(),'stderrSHA256':hashlib.sha256((proof/(label+'.stderr')).read_bytes()).hexdigest()}
 records.append(record);(proof/'commands.json').write_text(json.dumps(records,indent=2))
 if error or actual!=expected_exit:raise RuntimeError((label,actual,expected_exit,error))
 return (proof/(label+'.stdout')).read_text()
def git(label,*args):return command(label,['git',*args],source,timeout=120).strip()
def tracked(label):
 data=command(label+'-git-tree',['git','ls-tree','-r','-z',expected['head']],source,timeout=120);result={}
 for entry in data.split('\0'):
  if not entry:continue
  metadata,name=entry.split('\t',1);mode,kind,oid=metadata.split()
  if kind!='blob':raise RuntimeError('unexpected submodule')
  path=source/name;raw=os.fsencode(os.readlink(path)) if mode=='120000' else path.read_bytes()
  actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
  if actual!=oid:raise RuntimeError('checkout bytes differ from Git blob: '+name)
  result[name]={'gitBlob':actual,'sha256':hashlib.sha256(raw).hexdigest()}
 (proof/(label+'-tracked.json')).write_text(json.dumps(result,indent=2));return result
before=None;fixture=source/manifest['fixturePath'];injected=False
try:
 (proof/'harness-hashes.json').write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in Path(__file__).parent.iterdir() if f.is_file()},indent=2))
 if platform.system()!='Linux' or os.environ.get('RUNNER_OS')!='Linux':raise RuntimeError('native Linux required')
 version=command('go-version-initial',['go','version'],source,timeout=120).strip()
 if version!='go version go1.26.4 linux/amd64':raise RuntimeError('pinned native Go mismatch')
 runtime={'sourceRoot':str(source),'GOFLAGS':os.environ.get('GOFLAGS'),'GOMAXPROCS':os.environ.get('GOMAXPROCS'),'GOTOOLCHAIN':os.environ.get('GOTOOLCHAIN'),'system':platform.system(),'machine':platform.machine(),'uname':command('native-uname',['uname','-a'],source,timeout=120).strip(),'goVersion':version,'goEnv':json.loads(command('go-env',['go','env','-json','GOOS','GOARCH','GOVERSION','CGO_ENABLED'],source,timeout=120))}
 (proof/'runtime.json').write_text(json.dumps(runtime,indent=2))
 if git('source-head-initial','rev-parse','HEAD')!=expected['head'] or git('source-tree-initial','rev-parse','HEAD^{tree}')!=expected['tree']:raise RuntimeError('immutable source mismatch')
 git('source-diff-initial','diff','--exit-code')
 git('source-index-initial','diff','--cached','--exit-code')
 if a.phase=='fixed' and git('source-parent','rev-parse','HEAD^')!=manifest['phases']['baseline']['head']:raise RuntimeError('fixed parent mismatch')
 before=tracked('before')
 if a.phase=='fixed':
  for path,sha in manifest['fixedSourceHashes'].items():
   if hashlib.sha256((source/path).read_bytes()).hexdigest()!=sha:raise RuntimeError('frozen source hash mismatch')
 test=Path(__file__).with_name('terminal_cells_test.go').read_bytes()
 if hashlib.sha256(test).hexdigest()!=manifest['fixtureSHA256']:raise RuntimeError('reviewed fixture hash mismatch')
 if a.phase=='baseline' and fixture.exists():raise RuntimeError('baseline unexpectedly has regression')
 if a.phase=='fixed' and fixture.read_bytes()!=test:raise RuntimeError('candidate fixture differs')
 cli=source/'cli/beacon'
 command('cli-build-real-hooks',['make','build'],cli)
 binaries=[source/'cli/beacon-hooks/beacon-hooks',cli/'internal/embedded/hooks.bin',cli/'beacon']
 if binaries[0].read_bytes()!=binaries[1].read_bytes() or any(not f.read_bytes().startswith(b'\x7fELF') for f in binaries):raise RuntimeError('actual native hooks/CLI payload not built')
 (proof/'build-binaries.json').write_text(json.dumps({str(f.relative_to(source)):{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in binaries},indent=2))
 command('actual-cli-version',[str(cli/'beacon'),'version'],cli,timeout=120)
 command('actual-cli-traces-help',[str(cli/'beacon'),'endpoint','traces','--help'],cli,timeout=120)
 inventories={};methods={};listed_packages={}
 for name,lane in manifest['lanes'].items():
  cwd=source/lane['module'];scope=lane['scope'];inventory=set(command(name+'-packages',['go','list',scope],cwd).splitlines())
  if not inventory:raise RuntimeError('empty package inventory')
  inventories[name]=sorted(inventory)
  argv=['go','test','-json','-count=1','-list','^(Test|Example|Fuzz)']+(['-race'] if lane['race'] else [])+[scope]
  roots,packages=list_tests(command(name+'-pristine-list',argv,cwd),inventory);methods[name]=sorted(roots);listed_packages[name]=packages
 (proof/'inventories.json').write_text(json.dumps({'packages':inventories,'listedMethods':methods,'listedPackageOutcomes':listed_packages},indent=2))
 if a.phase=='baseline':fixture.write_bytes(test);injected=True
 (proof/'fixture.json').write_text(json.dumps({'path':manifest['fixturePath'],'sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'transplanted':injected},indent=2))
 for name,lane in manifest['lanes'].items():
  cwd=source/lane['module'];argv=['go','test','-json','-count=1']+(['-race'] if lane['race'] else [])+[lane['scope']]
  expected_exit=1 if a.phase=='baseline' and lane['affected'] else 0
  cases,packages=parse(command(name+'-tests',argv,cwd,expected_exit),set(inventories[name]))
  roots={k for k in cases if '/' not in k.split('::',1)[1]};want=set(methods[name])|(ROOTS if a.phase=='baseline' and lane['affected'] else set())
  if roots!=want:raise RuntimeError('listed original method omitted: '+name)
  if lane['affected']:
   expected_new=NEW if a.phase=='baseline' else {k:('pass','') for k in NEW}
   if any(cases.get(k)!=v for k,v in expected_new.items()):raise RuntimeError('literal16 new outcomes mismatch: '+name)
  if any(v[0]=='fail' for k,v in cases.items() if not(lane['affected'] and k in NEW)):raise RuntimeError('unrelated original failure')
  expected_packages={k:tuple(v) for k,v in listed_packages[name].items()}
  if a.phase=='baseline' and lane['affected']:expected_packages[PKG]=('fail','')
  if packages!=expected_packages:raise RuntimeError('unrelated package outcome: '+name)
 if fixture.read_bytes()!=test:raise RuntimeError('regression fixture changed during native tests')
 (proof/'fixture-after.json').write_text(json.dumps({'path':manifest['fixturePath'],'sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'transplanted':injected},indent=2))
 if injected:fixture.unlink();injected=False
 if command('go-version-final',['go','version'],source,timeout=120).strip()!=version:raise RuntimeError('runtime changed')
 result={'status':'PASS_NATIVE_PHASE_PENDING_COMPARISON','phase':a.phase,'head':expected['head'],'tree':expected['tree'],'scope':'five native Go modules plus endpoint race; Linux only; paid sandbox not run'}
except Exception as error:result={'status':'FAIL','phase':a.phase,'error':str(error)}
finally:
 if injected:
  try:
   if fixture.read_bytes()!=test:raise RuntimeError('transplanted fixture mutated')
  except Exception as error:result={'status':'FAIL','phase':a.phase,'error':str(error)}
  if fixture.exists():fixture.unlink()
 try:
  if before is not None and before!=tracked('after'):raise RuntimeError('tracked bytes changed')
  if git('source-head-final','rev-parse','HEAD')!=expected['head']:raise RuntimeError('head changed')
  git('source-diff-final','diff','--exit-code')
  git('source-index-final','diff','--cached','--exit-code')
 except Exception as error:result={'status':'FAIL','phase':a.phase,'error':str(error)}
 (proof/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if result['status']!='PASS_NATIVE_PHASE_PENDING_COMPARISON':raise SystemExit(1)
