#!/usr/bin/env python3
"""Install the private headless engine and compatibility helper; never edits TCC."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--with-webkit', action='store_true', help='Install the headless WebKit engine used for safari requests')
args = parser.parse_args()
state = Path.home() / '.blacklabel/isolated-browser'
state.mkdir(parents=True, exist_ok=True, mode=0o700)
state.chmod(0o700)
bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
node = os.environ.get('BL_BROWSER_NODE') or shutil.which('node') or str(bundled/'bin/node')
playwright = os.environ.get('BL_BROWSER_PLAYWRIGHT')
if not playwright:
    candidate = bundled/'node_modules/playwright'
    if candidate.is_dir(): playwright = str(candidate)
    else:
        result = subprocess.run([node,'-p',"require.resolve('playwright')"],capture_output=True,text=True,check=True)
        playwright = result.stdout.strip()
worker = state/'headless.mjs'
shutil.copy2(root/'server/headless.mjs', worker)
shutil.copy2(root/'server/workflow.mjs', state/'workflow.mjs')
shutil.copy2(root/'server/execution.mjs', state/'execution.mjs')
shutil.copy2(root/'server/checkpoint.mjs', state/'checkpoint.mjs')
runtime = {'node':str(Path(node).resolve()),'playwright':playwright,'worker':str(worker)}
temporary = state/'runtime.json.new'
temporary.write_text(json.dumps(runtime,indent=2)+'\n'); temporary.chmod(0o600)
os.replace(temporary,state/'runtime.json')
if args.with_webkit:
    package = Path(playwright)
    cli = package/'cli.js' if package.is_dir() else package.parent/'cli.js'
    subprocess.run([node,str(cli),'install','webkit'],check=True,
                   env={**os.environ,'PLAYWRIGHT_SKIP_BROWSER_GC':'1'})

app = Path.home()/'Applications/Black Label Browser Bridge.app'
source = root/'native/BrowserBridge.swift'
with tempfile.TemporaryDirectory(prefix='bl-browser-build-') as temp:
    binary = Path(temp)/'BrowserBridge'
    subprocess.run(['xcrun','swiftc',str(source),'-O','-module-cache-path',str(Path(temp)/'modules'),'-o',str(binary)],check=True)
    (app/'Contents/MacOS').mkdir(parents=True,exist_ok=True)
    info={'CFBundleIdentifier':'com.blacklabel.browser-bridge','CFBundleName':'Black Label Browser Bridge',
          'CFBundleDisplayName':'Black Label Browser Bridge','CFBundleVersion':'3','CFBundleShortVersionString':'1.1.0',
          'CFBundleExecutable':'BrowserBridge','CFBundlePackageType':'APPL','LSUIElement':True}
    with (app/'Contents/Info.plist').open('wb') as stream: plistlib.dump(info,stream)
    staged=app/'Contents/MacOS/BrowserBridge.new';shutil.copy2(binary,staged)
    os.replace(staged,app/'Contents/MacOS/BrowserBridge')
    subprocess.run(['/usr/bin/codesign','--force','--sign','-','--identifier','com.blacklabel.browser-bridge',str(app)],check=True,capture_output=True)
receipt={'mode':'isolated-headless','app':str(app),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
         'worker_sha256':hashlib.sha256(worker.read_bytes()).hexdigest(),
         'workflow_sha256':hashlib.sha256((state/'workflow.mjs').read_bytes()).hexdigest(),
         'checkpoint_sha256':hashlib.sha256((state/'checkpoint.mjs').read_bytes()).hexdigest(),
         'execution_sha256':hashlib.sha256((state/'execution.mjs').read_bytes()).hexdigest(),
         'binary_sha256':hashlib.sha256((app/'Contents/MacOS/BrowserBridge').read_bytes()).hexdigest(),
         'permission_changes':False,'desktop_input':False,'extension_required':False,'owner_debugging_toggle_required':False}
(state/'install.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
