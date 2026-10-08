"""Authorized release smoke test: synthetic temporary draft, no mail or model calls."""
import json
from datetime import datetime, timezone
from pathlib import Path
import httpx

origin = "https://resume.yikuaibanz.cn"
checks = []

def expect(name, response, status):
    actual = response.status_code
    checks.append({"check": name, "expected_status": status, "actual_status": actual})
    if actual != status:
        raise RuntimeError(f"{name}: expected {status}, got {actual}")
    return response

with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=30) as visitor, httpx.Client(base_url=origin, timeout=30) as other:
    sid = None
    try:
        health=expect("health",visitor.get("/healthz"),200).json()
        me=expect("guest-enabled",visitor.get("/api/account/me"),200).json()
        assert me["guest_allowed"] and me["require_account"] and not me["authenticated"]
        sample=expect("anonymous-sample",visitor.get("/api/resume/sample"),200).json()
        expect("anonymous-template-preview",visitor.post("/api/resume/render/t001-jianyue",json=sample),200)
        created=expect("guest-create",visitor.post("/api/chat/conversations"),200)
        sid=created.json()["session_id"]
        cookie=created.headers.get("set-cookie","")
        assert "HttpOnly" in cookie and "Secure" in cookie and "Max-Age" not in cookie
        current=expect("guest-read",visitor.get("/api/resume/current",params={"session_id":sid}),200).json()
        data={"basic_info":{"name":"GUEST_DEPLOYMENT_SMOKE"},"projects":[{"name":"虚构发布检查","description":"仅用于验证游客编辑和预览，不涉及真实求职者。"}]}
        saved=expect("guest-edit",visitor.put("/api/resume/current",json={"session_id":sid,"expected_revision":current["revision"],"resume_data":data}),200).json()
        expect("guest-own-preview",visitor.post("/api/resume/render/t001-jianyue",params={"session_id":sid},json=saved["data"]),200)
        expect("other-browser-denied",other.get("/api/resume/current",params={"session_id":sid}),404)
        expect("cross-origin-write-denied",visitor.put("/api/resume/current",headers={"Origin":"https://example.invalid"},json={"session_id":sid,"expected_revision":saved["revision"],"resume_data":data}),403)
        for name,path in [("history-needs-login","/api/chat/conversations"),("memory-needs-login","/api/profile"),("generic-word-needs-login","/api/chat/export/docx?session_id="+sid)]:
            expect(name,visitor.get(path),401)
        for name,path in [("word-needs-login","/api/resume/export/docx/t001-jianyue"),("pdf-needs-login","/api/resume/render/t001-jianyue?export=true")]:
            expect(name,visitor.post(path,params={"session_id":sid, **({"export":"true"} if name=="pdf-needs-login" else {})},json=saved["data"]),401)
    finally:
        if sid:
            expect("synthetic-draft-cleanup",visitor.delete("/api/chat/session/"+sid),200)
output={"checked_at":datetime.now(timezone.utc).isoformat(),"health":health,"account_flags":me,"checks":checks,"passed":len(checks),"real_mail_sent":False,"model_called":False}
Path(__file__).with_name("public-checks.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"passed":len(checks),"health":health,"guest_allowed":me["guest_allowed"]},ensure_ascii=False))
