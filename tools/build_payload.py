import base64
import gzip
import pathlib
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / "helper" / "dyxhs_helper.py"
TEMPLATE = ROOT / "action" / "main.template.cs"
OUTPUT = ROOT / "action" / "main.cs"

payload = base64.b64encode(gzip.compress(HELPER.read_bytes(), 9)).decode("ascii")
wrapped = "\n".join(textwrap.wrap(payload, 110))
source = TEMPLATE.read_text(encoding="utf-8")
if "__HELPER_PAYLOAD_PLACEHOLDER__" not in source:
    raise SystemExit("template is missing __HELPER_PAYLOAD_PLACEHOLDER__")
OUTPUT.write_text(source.replace("__HELPER_PAYLOAD_PLACEHOLDER__", wrapped), encoding="utf-8")
print(f"built {OUTPUT.name}: helper={len(HELPER.read_bytes())} bytes, payload={len(payload)} chars")
