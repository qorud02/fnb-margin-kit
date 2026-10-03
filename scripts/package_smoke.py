"""Exercise file-based margin reports in a non-root image or isolated wheel."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

parser=argparse.ArgumentParser()
mode=parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--container')
mode.add_argument('--python')
mode.add_argument('--source',type=Path,help='Local functional preflight only; no installed-wheel claim')
parser.add_argument('--console')
args=parser.parse_args()
if args.python and not args.console:
    parser.error('--python requires --console')
root=Path.cwd().resolve()
version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
clean_env={key:value for key,value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME','PYTHONOPTIMIZE'}}
clean_env['PYTHONIOENCODING']='utf-8'
if args.source:
    clean_env['PYTHONPATH']=str(args.source.resolve()/'src')
checks=[]
with tempfile.TemporaryDirectory(prefix='fnb-package-smoke-') as directory:
    temp=Path(directory)
    temp.chmod(0o755)
    output=temp/'output'
    output.mkdir()
    output.chmod(0o777) # Disposable synthetic outputs, writable by image UID 10001.
    header='menu,category,price_gross,vat_rate,ingredient_cost,packaging_cost,platform_fee_rate,units\n'
    row='item,store,5500,0.10,1200,100,0,100\n'
    payloads={
        'empty.csv':b'',
        'bad-header.csv':b'menu,price\nitem,1\n',
        'ragged.csv':(header+'item,store,5500\n').encode(),
        'nonfinite.csv':(header+row.replace('5500','NaN')).encode(),
        'duplicate.csv':(header+row+row).encode(),
        'zero.csv':(header+'negative,store,0,0.10,700,100,0.03,0\n').encode(),
        'source.csv':(header+row).encode(),
    }
    for name,data in payloads.items():
        (temp/name).write_bytes(data)
        (temp/name).chmod(0o644)
    alias=temp/'alias'
    alias.mkdir()
    alias.chmod(0o755)
    (alias/'report.json').write_bytes((temp/'source.csv').read_bytes())
    (alias/'report.json').chmod(0o644)
    linked=temp/'hardlink'
    linked.mkdir()
    linked.chmod(0o755)
    os.link(temp/'source.csv',linked/'report.json')
    before_source=(temp/'source.csv').read_bytes()
    before_alias=(alias/'report.json').read_bytes()

    if args.container:
        base=['docker','run','--rm','--platform','linux/amd64','--read-only','--network','none',
              '--cap-drop','ALL','--security-opt','no-new-privileges',
              '--mount','type=bind,source='+str(root)+',target=/work,readonly',
              '--mount','type=bind,source='+str(temp)+',target=/fixtures,readonly',
              '--mount','type=bind,source='+str(output)+',target=/output',
              '--workdir','/work']
        prefix=base+[args.container]
        fixture=lambda name:'/work/examples/'+name
        extra=lambda name:'/fixtures/'+name
        out=lambda name:'/output/'+name
    else:
        prefix=[sys.executable,'-m','fnb_margin_kit.cli'] if args.source else [str(Path(args.console).absolute())]
        fixture=lambda name:str(root/'examples'/name)
        extra=lambda name:str(temp/name)
        out=lambda name:str(output/name)

    def run(arguments,expected,label):
        result=subprocess.run(prefix+arguments,cwd=temp,env=clean_env,capture_output=True,text=True,encoding='utf-8',timeout=180)
        assert result.returncode==expected,(label,expected,result.returncode,result.stdout,result.stderr)
        checks.append(label)
        return result

    def report(name,arguments):
        destination=output/name
        destination.mkdir()
        destination.chmod(0o777)
        run(arguments+['--output-dir',out(name)],0,name)
        assert (destination/'report.md').is_file()
        return json.loads((destination/'report.json').read_text(encoding='utf-8'))

    help_text=run(['--help'],0,'console-help').stdout
    assert '--fixed-cost' in help_text and '--output-dir' in help_text
    original=report('original-menu',[fixture('menu.csv')])
    assert original['total_units']==190 and Decimal(original['totals']['net_sales'])==Decimal('770000')
    assert Decimal(original['totals']['contribution'])==Decimal('512000')

    comparison=report('store-versus-delivery',[fixture('store-versus-delivery.csv')])
    assert comparison['total_units']==140 and len(comparison['menus'])==2
    rows={row['category']:row for row in comparison['menus']}
    assert set(rows)=={'매장','배달'} and {row['menu'] for row in comparison['menus']}=={'카페라테'}
    for category,unit,total,fee in [('매장','3700','370000','0'),('배달','2675','107000','825')]:
        assert Decimal(rows[category]['net_price_per_unit'])==Decimal('5000')
        assert Decimal(rows[category]['contribution_per_unit'])==Decimal(unit)
        assert Decimal(rows[category]['total_contribution'])==Decimal(total)
        assert Decimal(rows[category]['platform_fee_per_unit'])==Decimal(fee)
    for key,value in {'gross_sales':'770000','net_sales':'700000','ingredient_cost':'168000',
                      'packaging_cost':'22000','platform_fees':'33000','variable_cost':'223000','contribution':'477000'}.items():
        assert Decimal(comparison['totals'][key])==Decimal(value),(key,comparison)
    assert 'fixed_cost_scenario' not in comparison

    fixed=report('specified-fixed-cost',[fixture('store-versus-delivery.csv'),'--fixed-cost','300000'])
    assert Decimal(fixed['fixed_cost_scenario']['specified_fixed_cost'])==Decimal('300000')
    assert Decimal(fixed['fixed_cost_scenario']['contribution_after_specified_fixed_cost'])==Decimal('177000')
    for name,published_name in [('store-versus-delivery','store-versus-delivery'),('specified-fixed-cost','store-versus-delivery-fixed-cost')]:
        for file_name in ('report.json','report.md'):
            assert (output/name/file_name).read_text(encoding='utf-8')==(root/'examples'/published_name/file_name).read_text(encoding='utf-8')

    zero=report('zero-units-negative-margin',[extra('zero.csv')])
    assert zero['total_units']==0 and zero['menus'][0]['margin_flag']=='negative'
    assert Decimal(zero['menus'][0]['contribution_per_unit'])==Decimal('-800')
    assert Decimal(zero['totals']['contribution'])==0
    for name in ('empty.csv','bad-header.csv','ragged.csv','nonfinite.csv','duplicate.csv'):
        run([extra(name),'--output-dir',out('invalid-'+name)],2,name)
        assert not (output/('invalid-'+name)).exists()
    guard=run([extra('alias/report.json'),'--output-dir',extra('alias')],2,'input-alias-protection')
    assert 'must not overwrite' in guard.stderr
    linked_guard=run([extra('source.csv'),'--output-dir',extra('hardlink')],2,'hardlink-protection')
    assert 'must not overwrite' in linked_guard.stderr
    assert (temp/'source.csv').read_bytes()==before_source and (alias/'report.json').read_bytes()==before_alias
    assert (linked/'report.json').read_bytes()==before_source
    assert not (alias/'report.md').exists() and not (linked/'report.md').exists()

    identity_code="import json,os,sys,fnb_margin_kit; from importlib.metadata import version; print(json.dumps({'path':fnb_margin_kit.__file__,'prefix':sys.prefix,'version':version('fnb-margin-kit'),'uid':getattr(os,'getuid',lambda:None)()}))"
    if args.container:
        identity_command=base+['--entrypoint','python',args.container,'-I','-c',identity_code]
    elif args.source:
        identity_command=[sys.executable,'-c',"import json,fnb_margin_kit; print(json.dumps({'path':fnb_margin_kit.__file__}))"]
    else:
        identity_command=[str(Path(args.python).absolute()),'-I','-c',identity_code]
    identity=subprocess.run(identity_command,cwd=temp,env=clean_env,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert identity.returncode==0,identity.stderr
    imported=json.loads(identity.stdout)
    if args.container:
        assert imported['version']==version and imported['uid']==10001 and imported['path'].startswith('/usr/local/lib/'),imported
        checks.append('non-root-installed-package-and-version')
    elif args.source:
        assert os.path.commonpath([imported['path'],str(args.source.resolve()/'src')])==str(args.source.resolve()/'src'),imported
        checks.append('explicit-source-import')
    else:
        environment=str(Path(args.python).absolute().parents[1])
        assert imported['version']==version and os.path.commonpath([imported['path'],environment])==environment,imported
        assert os.path.normcase(imported['prefix'])==os.path.normcase(environment),imported
        checks.append('isolated-wheel-import-and-version')
    if not args.container:
        interpreter=sys.executable if args.source else str(Path(args.python).absolute())
        command=[interpreter]+([] if args.source else ['-I'])+['-m','fnb_margin_kit.cli','--help']
        result=subprocess.run(command,cwd=temp,env=clean_env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert result.returncode==0 and '--fixed-cost' in result.stdout
        checks.append('module-help')
print(json.dumps({'mode':'container' if args.container else 'source' if args.source else 'wheel','version':version,
                  'version_check':'source pyproject only' if args.source else 'installed package metadata; CLI has no --version',
                  'input_mode':'CSV files; JSON and Markdown written to the selected output directory',
                  'checks':checks,'passed':len(checks)}))
