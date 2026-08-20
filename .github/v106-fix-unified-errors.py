from pathlib import Path

app_path = Path('frontend/static/app.js')
test_path = Path('backend/tests/test_v106_audit_contracts.py')

app = app_path.read_text()
old = """    if (failed.length) {\n      toast(`${handled} handled · ${failed.length} failed`, handled ? 'warn' : 'error');\n    } else {\n      toast(`${handled} item${handled === 1 ? '' : 's'} submitted`, 'success');\n    }\n"""
new = """    if (failed.length) {\n      const failureMessages = [...new Set(\n        failed.map(entry => String(entry.error?.message || 'Request failed'))\n      )];\n      if (!handled && failureMessages.length === 1) {\n        toast(sanitizeErrorMsg(failureMessages[0]), 'error');\n      } else {\n        toast(`${handled} handled · ${failed.length} failed`, handled ? 'warn' : 'error');\n      }\n    } else {\n      toast(`${handled} item${handled === 1 ? '' : 's'} submitted`, 'success');\n    }\n"""
if app.count(old) != 1:
    raise SystemExit(f'expected exactly one unified failure-toast block, found {app.count(old)}')
app = app.replace(old, new, 1)
app_path.write_text(app)

tests = test_path.read_text()
needle = """    assert \"async function addDebridLinks()\" not in js\n"""
addition = """    assert \"failureMessages.length === 1\" in js\n    assert \"sanitizeErrorMsg(failureMessages[0])\" in js\n"""
if addition not in tests:
    if tests.count(needle) != 1:
        raise SystemExit(f'expected exactly one dashboard contract insertion point, found {tests.count(needle)}')
    tests = tests.replace(needle, needle + addition, 1)
test_path.write_text(tests)
