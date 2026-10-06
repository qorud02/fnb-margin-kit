"""Exercise file-based margin reports in a non-root image or isolated wheel."""
import argparse
from decimal import Decimal
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from markdown_it import MarkdownIt


class TableCells(HTMLParser):
    def __init__(self, rendered):
        super().__init__(convert_charrefs=True)
        self.cells, self.current, self.nested_tags = [], None, []
        self.feed(rendered)
    def handle_starttag(self, tag, attrs):
        if self.current is not None:
            self.nested_tags.append(tag)
        if tag == 'td':
            self.current = []
    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)
    def handle_endtag(self, tag):
        if tag == 'td' and self.current is not None:
            self.cells.append(''.join(self.current))
            self.current = None

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
    literal_menu='![Latte](https://example.test/pixel.png) **bold** _em_ ~~old~~ `code` | \\'
    literal_category='[Store](https://example.test)'
    payloads={
        'empty.csv':b'',
        'bad-header.csv':b'menu,price\nitem,1\n',
        'ragged.csv':(header+'item,store,5500\n').encode(),
        'nonfinite.csv':(header+row.replace('5500','NaN')).encode(),
        'duplicate.csv':(header+row+row).encode(),
        'zero.csv':(header+'negative,store,0,0.10,700,100,0.03,0\n').encode(),
        'source.csv':(header+row).encode(),
        'costs.csv':b'category,additional_variable_cost\nstore,60000\n',
        'unknown-cost.csv':b'category,additional_variable_cost\nunknown,60000\n',
        'nonfinite-cost.csv':b'category,additional_variable_cost\nstore,NaN\n',
        'duplicate-cost.csv':b'category,additional_variable_cost\nstore,1\nstore,2\n',
        'html-names.csv':(header+'"</script><img src=x onerror=alert(1)>",store,5500,0.10,1200,100,0,1\n').encode(),
        'markdown-names.csv':(header+literal_menu+','+literal_category+',10,0,0,0,0,1\n').encode(),
        'markdown-costs.csv':('category,additional_variable_cost\n'+literal_category+',2\n').encode(),
        'cancellation.csv':(header
            +'Positive,store,1e24,0,0,0,0,1e24\n'
            +'Cent,store,0.01,0,0,0,0,1\n'
            +'Negative,store,0,0,1e24,0,0,1e24\n').encode(),
        'small-cost.csv':b'category,additional_variable_cost\nstore,0.02\n',
        'mismatched-plan.csv':(header+row.replace('item,','other,')).encode(),
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
    cost_alias=temp/'cost-alias'
    cost_alias.mkdir()
    cost_alias.chmod(0o755)
    (cost_alias/'report.md').write_bytes(payloads['costs.csv'])
    (cost_alias/'report.md').chmod(0o644)
    cost_linked=temp/'cost-hardlink'
    cost_linked.mkdir()
    cost_linked.chmod(0o755)
    os.link(temp/'costs.csv',cost_linked/'report.json')
    html_alias=temp/'html-alias'
    html_alias.mkdir()
    html_alias.chmod(0o755)
    (html_alias/'report.html').write_bytes(payloads['source.csv'])
    (html_alias/'report.html').chmod(0o644)
    html_linked=temp/'html-cost-hardlink'
    html_linked.mkdir()
    html_linked.chmod(0o755)
    os.link(temp/'costs.csv',html_linked/'report.html')
    plan_alias=temp/'plan-hardlink'
    plan_alias.mkdir()
    plan_alias.chmod(0o755)
    os.link(temp/'source.csv',plan_alias/'comparison.json')
    plan_cost_alias=temp/'plan-cost-hardlink'
    plan_cost_alias.mkdir()
    plan_cost_alias.chmod(0o755)
    os.link(temp/'costs.csv',plan_cost_alias/'comparison.md')

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
    assert all(option in help_text for option in ('--fixed-cost','--output-dir','--channel-costs','--html','--compare-menu','--compare-channel-costs'))
    original=report('original-menu',[fixture('menu.csv')])
    assert original['total_units']==190 and Decimal(original['totals']['net_sales'])==Decimal('770000')
    assert Decimal(original['totals']['contribution'])==Decimal('512000')
    assert not (output/'original-menu'/'report.html').exists()

    literal=report('literal-markdown-names',[extra('markdown-names.csv'),'--channel-costs',extra('markdown-costs.csv')])
    assert literal['menus'][0]['menu']==literal_menu and literal['menus'][0]['category']==literal_category
    literal_text=(output/'literal-markdown-names'/'report.md').read_text(encoding='utf-8')
    literal_html=MarkdownIt('commonmark').enable(['table','strikethrough']).render(literal_text)
    cells=TableCells(literal_html)
    assert not cells.nested_tags and len(cells.cells)==14, (cells.cells,cells.nested_tags)
    assert [cells.cells[i] for i in (1,2,9)]==[literal_menu,literal_category,literal_category], cells.cells

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

    channel=report('additional-channel-cost',[fixture('store-versus-delivery.csv'),
                   '--channel-costs',fixture('channel-costs.csv'),'--fixed-cost','300000'])
    assert channel['menus']==comparison['menus'] and channel['totals']==comparison['totals']
    costs=channel['channel_cost_scenario']
    categories={record['category']:record for record in costs['categories']}
    assert Decimal(costs['total_additional_variable_cost'])==Decimal('60000')
    assert Decimal(costs['contribution_after_additional_costs'])==Decimal('417000')
    assert Decimal(categories['매장']['contribution_after_additional_cost'])==Decimal('370000')
    assert Decimal(categories['배달']['contribution_after_additional_cost'])==Decimal('47000')
    assert Decimal(channel['fixed_cost_scenario']['contribution_after_specified_fixed_cost'])==Decimal('117000')
    assert channel['fixed_cost_scenario']['basis']==(
        'The supplied fixed cost is deducted after the additional channel costs. '
        'Other operating expenses and income tax remain excluded.'
    )
    assert '117,000.00' in (output/'additional-channel-cost'/'report.md').read_text(encoding='utf-8')
    for name in ('unknown-cost.csv','nonfinite-cost.csv','duplicate-cost.csv'):
        run([extra('source.csv'),'--channel-costs',extra(name),'--output-dir',out('invalid-'+name)],2,name)
        assert not (output/('invalid-'+name)).exists()
    cost_guard=run([extra('source.csv'),'--channel-costs',extra('cost-alias/report.md'),
                   '--output-dir',extra('cost-alias')],2,'channel-cost-input-alias-protection')
    assert 'must not overwrite' in cost_guard.stderr
    cost_link_guard=run([extra('source.csv'),'--channel-costs',extra('costs.csv'),
                        '--output-dir',extra('cost-hardlink')],2,'channel-cost-hardlink-protection')
    assert 'must not overwrite' in cost_link_guard.stderr
    assert (temp/'costs.csv').read_bytes()==payloads['costs.csv']
    assert (cost_alias/'report.md').read_bytes()==payloads['costs.csv']
    assert (cost_linked/'report.json').read_bytes()==payloads['costs.csv']
    assert not (cost_alias/'report.json').exists() and not (cost_linked/'report.md').exists()

    dashboard=report('offline-dashboard',[fixture('store-versus-delivery.csv'),
                     '--channel-costs',fixture('channel-costs.csv'),'--fixed-cost','300000','--html'])
    assert dashboard==channel
    for name in ('report.json','report.md'):
        assert (output/'offline-dashboard'/name).read_bytes()==(output/'additional-channel-cost'/name).read_bytes()
    html=(output/'offline-dashboard'/'report.html').read_text(encoding='utf-8')
    payload=json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',html,re.S).group(1))
    assert Decimal(payload['summary']['fixed_cost_scenario']['contribution_after_specified_fixed_cost'])==Decimal('117000')
    assert '117,000.00' in html and 'id="exact-values"' in html and '@media print' in html
    assert 'parseFloat' not in html and 'Number(' not in html and 'fetch(' not in html
    assert not re.search(r'<(?:script|link|img)\b[^>]*\b(?:src|href)\s*=',html,re.I)
    secure=report('escaped-html-names',[extra('html-names.csv'),'--html'])
    secure_html=(output/'escaped-html-names'/'report.html').read_text(encoding='utf-8')
    assert '<img' not in secure_html and '\\u003c/script\\u003e' in secure_html
    secure_payload=json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',secure_html,re.S).group(1))
    assert secure_payload['menus'][0]['menu']==secure['menus'][0]['menu']
    guard=run([extra('html-alias/report.html'),'--html','--output-dir',extra('html-alias')],2,'html-input-alias-protection')
    assert 'must not overwrite' in guard.stderr
    cost_guard=run([extra('source.csv'),'--channel-costs',extra('costs.csv'),'--html',
                   '--output-dir',extra('html-cost-hardlink')],2,'html-channel-cost-hardlink-protection')
    assert 'must not overwrite' in cost_guard.stderr
    assert (html_alias/'report.html').read_bytes()==payloads['source.csv']
    assert (html_linked/'report.html').read_bytes()==payloads['costs.csv']
    assert not (html_alias/'report.json').exists() and not (html_linked/'report.json').exists()

    scenario_base=report('scenario-baseline',[fixture('price-cost-scenarios/baseline.csv'),
                         '--channel-costs',fixture('price-cost-scenarios/baseline-channel-costs.csv'),
                         '--fixed-cost','300000','--html'])
    scenario_report=report('scenario-comparison',[fixture('price-cost-scenarios/baseline.csv'),
                           '--compare-menu',fixture('price-cost-scenarios/proposed.csv'),
                           '--channel-costs',fixture('price-cost-scenarios/baseline-channel-costs.csv'),
                           '--compare-channel-costs',fixture('price-cost-scenarios/proposed-channel-costs.csv'),
                           '--fixed-cost','300000','--html'])
    assert scenario_report==scenario_base
    for name in ('report.json','report.md','report.html'):
        assert (output/'scenario-comparison'/name).read_bytes()==(output/'scenario-baseline'/name).read_bytes()
    scenario=json.loads((output/'scenario-comparison'/'comparison.json').read_text(encoding='utf-8'))
    assert scenario['baseline']==scenario_base and (output/'scenario-comparison'/'comparison.md').is_file()
    summary=scenario['summary']
    for side,menu_total,after_channel,after_fixed in [('baseline','450100','437100','137100'),
                                                    ('proposed','458568','440568','140568')]:
        assert Decimal(summary[side]['contribution'])==Decimal(menu_total)
        assert Decimal(summary[side]['contribution_after_additional_costs'])==Decimal(after_channel)
        assert Decimal(summary[side]['contribution_after_specified_fixed_cost'])==Decimal(after_fixed)
    assert Decimal(summary['delta']['contribution_after_specified_fixed_cost'])==Decimal('3468')
    scenario_rows={row['category']:row for row in scenario['menus']}
    assert scenario_rows['매장']['retained_contribution_quantity']['min_units']==92
    assert scenario_rows['배달']['retained_contribution_quantity']['min_units']==35
    assert scenario_rows['배달']['retained_contribution_quantity']['current_units_meet_threshold']
    assert Decimal(scenario_rows['배달']['proposed']['platform_fee_per_unit'])==Decimal('1089')
    assert Decimal(scenario_rows['매장']['baseline']['net_sales'])==Decimal('500000')
    assert Decimal(scenario_rows['매장']['proposed']['net_sales'])==Decimal('495000')
    for label,arguments in [
        ('comparison-cost-flag-requires-menu',[extra('source.csv'),'--compare-channel-costs',extra('costs.csv')]),
        ('comparison-identity-mismatch',[extra('source.csv'),'--compare-menu',extra('mismatched-plan.csv')]),
    ]:
        run(arguments+['--output-dir',out(label)],2,label)
        assert not (output/label).exists()
    guard=run([extra('source.csv'),'--compare-menu',extra('source.csv'),
               '--output-dir',extra('plan-hardlink')],2,'proposed-menu-comparison-output-hardlink-protection')
    assert 'must not overwrite' in guard.stderr and (temp/'source.csv').read_bytes()==before_source
    guard=run([extra('source.csv'),'--compare-menu',extra('source.csv'),'--compare-channel-costs',extra('costs.csv'),
               '--output-dir',extra('plan-cost-hardlink')],2,'proposed-cost-comparison-output-hardlink-protection')
    assert 'must not overwrite' in guard.stderr and (temp/'costs.csv').read_bytes()==payloads['costs.csv']
    assert not (plan_alias/'report.json').exists() and not (plan_cost_alias/'report.json').exists()

    exact=report('exact-cancellation',[extra('cancellation.csv'),'--channel-costs',extra('small-cost.csv'),
                 '--fixed-cost','0.03','--html'])
    assert Decimal(exact['totals']['contribution'])==Decimal('0.01')
    scenario=exact['channel_cost_scenario']
    assert Decimal(scenario['categories'][0]['contribution_before_additional_cost'])==Decimal('0.01')
    assert Decimal(scenario['contribution_after_additional_costs'])==Decimal('-0.01')
    assert Decimal(exact['fixed_cost_scenario']['contribution_after_specified_fixed_cost'])==Decimal('-0.04')
    exact_html=(output/'exact-cancellation'/'report.html').read_text(encoding='utf-8')
    exact_payload=json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',exact_html,re.S).group(1))
    assert Decimal(exact_payload['categories'][0]['contribution_after_additional_cost'])==Decimal('-0.01')

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
        assert result.returncode==0 and all(option in result.stdout for option in ('--fixed-cost','--channel-costs','--html','--compare-menu','--compare-channel-costs'))
        checks.append('module-help')
print(json.dumps({'mode':'container' if args.container else 'source' if args.source else 'wheel','version':version,
                  'version_check':'source pyproject only' if args.source else 'installed package metadata; CLI has no --version',
                  'input_mode':'CSV files; JSON and Markdown written to the selected output directory',
                  'checks':checks,'passed':len(checks)}))
