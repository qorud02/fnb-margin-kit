"""Validate the maintained destination and release version before publishing."""
import os
from pathlib import Path
import re
import tomllib

project=tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']
if project['name']!='fnb-margin-kit' or project['scripts'].get('fnb-margin')!='fnb_margin_kit.cli:main':
    raise SystemExit('Package name or console entry point differs')
version=project['version']
event=os.environ['GITHUB_EVENT_NAME']
ref=os.environ['GITHUB_REF']
if event=='push' and ref.startswith('refs/tags/v'):
    requested=ref.removeprefix('refs/tags/v')
elif event=='workflow_dispatch' and ref=='refs/heads/main':
    requested=os.environ.get('REQUESTED_VERSION','')
else:
    raise SystemExit('Publishing requires a version tag or manual dispatch on main')
if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',requested) or requested!=version:
    raise SystemExit('Requested version must match pyproject.toml')
image='ghcr.io/'+os.environ['GITHUB_REPOSITORY'].lower()
if image!='ghcr.io/qorud02/fnb-margin-kit':
    raise SystemExit('Package destination must match the maintained repository')
with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8',newline='\n') as output:
    output.write('version='+version+'\nimage='+image+'\n')
print('Validated package version '+version)
