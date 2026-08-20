#!/usr/bin/env python3
# Temporary one-shot v1.0.5 transform loader; removed from the validated commit.
from __future__ import annotations

import base64
import hashlib
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
PAYLOAD_SHA256 = "c966acb2374140806e0a97059ffa0f18430ef081e4af26a980f1205e624fac65"
SOURCE_SHA256 = "3cde6b08a8acc898a3b08e44a6acd9716b135074c24403c5a42af759cb2854e0"

chunks = [TOOLS / f"v105_fix4_payload_{i}.txt" for i in range(7)]
payload = "".join(path.read_text(encoding="utf-8").strip() for path in chunks)
if hashlib.sha256(payload.encode("ascii")).hexdigest() != PAYLOAD_SHA256:
    raise RuntimeError("v1.0.5 fix4 payload checksum mismatch")

source = zlib.decompress(base64.b64decode(payload, validate=True))
if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
    raise RuntimeError("v1.0.5 fix4 source checksum mismatch")

exec(compile(source, "tools/v105_refactor_fix4.py", "exec"))

# FastAPI expects a single async context-manager wrapper around the lifespan
# generator. The one-shot transform can encounter the upstream decorator and
# must not add a second wrapper.
main_path = ROOT / "backend/main.py"
main_src = main_path.read_text(encoding="utf-8")
main_src = main_src.replace(
    "@asynccontextmanager\n@asynccontextmanager\nasync def lifespan(app: FastAPI):",
    "@asynccontextmanager\nasync def lifespan(app: FastAPI):",
)
main_src = main_src.replace(
    "# persistence initialization on startup\n_PG_CONNECT_RETRIES = 15\n_PG_CONNECT_DELAY   = 10.0  # seconds between attempts (15 × 10s = 150s max wait)\n\n\n",
    "# persistence initialization on startup\n\n",
)
main_path.write_text(main_src, encoding="utf-8")

# Lock the lifecycle regression into the architecture contract rather than
# relying only on container smoke to catch it.
arch_test_path = ROOT / "backend/tests/test_v105_architecture.py"
arch_test = arch_test_path.read_text(encoding="utf-8")
if "def test_fastapi_lifespan_has_single_context_manager_boundary():" not in arch_test:
    arch_test = arch_test.rstrip("\n") + "\n\n\ndef test_fastapi_lifespan_has_single_context_manager_boundary():\n    main = text(\"backend/main.py\")\n    assert \"@asynccontextmanager\\n@asynccontextmanager\\nasync def lifespan\" not in main\n    assert main.count(\"@asynccontextmanager\\nasync def lifespan(app: FastAPI):\") == 1\n    assert \"_PG_CONNECT_RETRIES\" not in main\n    assert \"_PG_CONNECT_DELAY\" not in main\n"
    arch_test_path.write_text(arch_test, encoding="utf-8")

# Keep transformed text files compatible with git diff --check: exactly one
# newline at EOF, not an extra blank line introduced by the one-shot edits.
for rel in (
    ".env.example",
    "backend/main.py",
    "backend/services/manager_v2.py",
    "backend/services/transfer_control.py",
    "backend/tests/test_config_validator.py",
    "backend/tests/test_v105_architecture.py",
):
    path = ROOT / rel
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n") + "\n", encoding="utf-8")

# The payload transport is build scaffolding only. Remove it and record those
# deletions so the validated architecture commit cannot retain the chunks.
manifest = ROOT / ".v105_changed_paths"
changed = {line.strip() for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()}
changed.update({"backend/main.py", "backend/tests/test_v105_architecture.py"})
for path in chunks:
    rel = path.relative_to(ROOT).as_posix()
    path.unlink()
    changed.add(rel)
manifest.write_text("\n".join(sorted(changed)) + "\n", encoding="utf-8")
