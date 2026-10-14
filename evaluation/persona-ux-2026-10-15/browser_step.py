"""Drive only visible, ordinary user interactions in isolated test sessions."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
case, action = sys.argv[1:3]
fixtures = json.loads((ROOT / "fixtures.json").read_text())
if action in fixtures[case]:
    text = fixtures[case][action]
    code = "async (page) => { await page.getByRole('textbox').fill(" + json.dumps(text, ensure_ascii=False) + "); await page.getByRole('button', { name: '发送', exact: true }).click(); }"
elif action == "capture":
    code = "async (page) => { return {text:await page.locator('body').innerText(),frames:await Promise.all(page.frames().filter(f=>f!==page.mainFrame()).map(async f=>({text:await f.locator('body').innerText().catch(()=>'' )})))}; }"
elif action == "resume":
    code = "async (page) => { await page.getByRole('tab', {name:'写简历',exact:true}).click(); }"
else:
    raise SystemExit("Unknown action")
started = time.time()
result = subprocess.run(["playwright-cli", "-s=resume-ux-" + case, "run-code", code], text=True, capture_output=True)
stamp = time.strftime("%H%M%S")
output = re.sub(r"([?&]session=)[0-9a-f-]+", r"\1[REDACTED]", result.stdout + result.stderr)
(ROOT / f"{case}-{action}-{stamp}.log").write_text(output)
if action == "capture" and "### Result\n" in output:
    data = json.loads(output.split("### Result\n", 1)[1].split("\n### Ran", 1)[0])
    texts = []
    for frame in data["frames"]:
        value = frame["text"].split("(() => {")[0]
        value = "\n".join(s.strip() for s in value.splitlines() if s.strip())
        if value and "胡话简历 / 简历编辑" not in value and value not in texts:
            texts.append(value)
    data["preview_texts"] = texts
    (ROOT / f"{case}-{action}-{stamp}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({"page_tail": data["text"][-5000:], "previews": texts}, ensure_ascii=False))
else:
    print(output)
print(result.stderr, file=sys.stderr)
print(f"elapsed_seconds={time.time()-started:.3f}")
raise SystemExit(result.returncode)
