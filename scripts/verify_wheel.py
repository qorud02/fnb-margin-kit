"""Verify src-layout code bytes, dependency-free metadata, entry point and MIT license."""
import configparser
from email.parser import Parser
import hashlib
from pathlib import Path
import sys
import tomllib
from zipfile import ZipFile

def check(condition,message):
    if not condition:
        raise SystemExit(message)

folder=Path(sys.argv[1])
wheels=list(folder.glob('fnb_margin_kit-*.whl'))
check(len(wheels)==1,'Expected exactly one fnb-margin-kit wheel')
wheel=wheels[0]
project=tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']
with ZipFile(wheel) as archive:
    names=archive.namelist()
    source={path.relative_to('src').as_posix():path for path in Path('src/fnb_margin_kit').rglob('*.py')}
    packaged={name for name in names if name.startswith('fnb_margin_kit/')}
    check(packaged==set(source),'Wheel package file set differs from source')
    for name,path in source.items():
        check(archive.read(name)==path.read_bytes(),'Wheel source differs: '+name)
    metadata=[name for name in names if name.endswith('.dist-info/METADATA')]
    check(len(metadata)==1,'Expected exactly one distribution metadata file')
    headers=Parser().parsestr(archive.read(metadata[0]).decode('utf-8'))
    check(headers['Name']==project['name'] and headers['Version']==project['version'],'Wheel name or version differs')
    check(headers['Requires-Python']==project['requires-python'],'Python requirement differs')
    check(not project.get('dependencies') and not headers.get_all('Requires-Dist'),'Runtime dependencies were added')
    check(headers['License-Expression']=='MIT' and headers.get_all('License-File')==['LICENSE'],'Wheel MIT license metadata differs')
    entries=[name for name in names if name.endswith('.dist-info/entry_points.txt')]
    check(len(entries)==1,'Expected console entry point metadata')
    config=configparser.ConfigParser()
    config.read_string(archive.read(entries[0]).decode('utf-8'))
    check(dict(config['console_scripts'])==project['scripts'],'Console entry point differs')
    licenses=[name for name in names if name.endswith('.dist-info/licenses/LICENSE')]
    check(len(licenses)==1 and archive.read(licenses[0])==Path('LICENSE').read_bytes(),'Wheel license bytes differ')
digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
(folder/'SHA256SUMS').write_text(digest+'  '+wheel.name+'\n',encoding='utf-8',newline='\n')
print('Verified wheel '+wheel.name+' SHA256 '+digest)
