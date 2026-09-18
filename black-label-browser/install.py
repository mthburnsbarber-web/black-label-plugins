#!/usr/bin/env python3
"""Compile and install only this plugin's native helper; never edits TCC."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parent
app = Path.home() / 'Applications/Black Label Browser Bridge.app'
source = root / 'native/BrowserBridge.swift'
state = Path.home() / '.blacklabel/native-browser'
state.mkdir(parents=True, exist_ok=True, mode=0o700)
with tempfile.TemporaryDirectory(prefix='bl-browser-build-') as tmp:
    binary = Path(tmp) / 'BrowserBridge'
    subprocess.run(['xcrun','swiftc',str(source),'-O','-o',str(binary),'-framework','AppKit','-framework','ApplicationServices'],check=True)
    (app/'Contents/MacOS').mkdir(parents=True,exist_ok=True)
    info={'CFBundleIdentifier':'com.blacklabel.browser-bridge','CFBundleName':'Black Label Browser Bridge',
          'CFBundleDisplayName':'Black Label Browser Bridge','CFBundleVersion':'1','CFBundleShortVersionString':'1.0.0',
          'CFBundleExecutable':'BrowserBridge','CFBundlePackageType':'APPL','LSUIElement':True,
          'NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication'}
    with (app/'Contents/Info.plist').open('wb') as f:plistlib.dump(info,f)
    shutil.copy2(binary,app/'Contents/MacOS/BrowserBridge')
    subprocess.run(['/usr/bin/codesign','--force','--sign','-','--identifier','com.blacklabel.browser-bridge',str(app)],check=True,capture_output=True)
receipt={'app':str(app),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
         'binary_sha256':hashlib.sha256((app/'Contents/MacOS/BrowserBridge').read_bytes()).hexdigest(),
         'permission_changes':False,'chrome_extension_required':False,'apple_events_required':False}
(state/'install.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
