# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/newlife/GitHub/winter-reset/vpn/vpn_orchestrator/tray_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['analyze_db', 'config', 'daemon', 'debug_start', 'main', 'manage_nodes', 'orchestrator', 'test_admin', 'tray_app', 'adapters.outbound_builder', 'adapters.xray_config', 'adapters', 'adapters.compatibility.singbox', 'adapters.compatibility', 'core.config_builder', 'core.db_manager', 'core.logging_config', 'core.runtime_manager', 'core.state', 'core.system_proxy', 'core', 'models.profile', 'models', 'services.browser_launcher', 'services.node_switcher', 'services.proxy_checker', 'services', 'ui.panels', 'ui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VPNOrchestrator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
