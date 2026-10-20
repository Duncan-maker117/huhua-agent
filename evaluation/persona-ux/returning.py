"""已有档案的合成老用户；仅由离线测试或显式指定的本地回放数据库预置。"""

from datetime import datetime, timedelta, timezone
import hashlib
from http.cookiejar import Cookie
from importlib import import_module
import secrets
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

FIRST = "你看看我的经历有没有什么可以直接用的"
ROLE = "AI 应用开发实习"
FACTS = [
    ("basic", "本人", "name", "林知远"),
    ("basic", "本人", "location", "深圳"),
    ("basic", "本人", "phone", "13900001234"),
    ("basic", "本人", "email", "returning@example.test"),
    ("education", "青川大学", "school", "青川大学"),
    ("education", "青川大学", "major", "软件工程"),
    ("education", "青川大学", "degree", "本科"),
    ("education", "青川大学", "end_date", "2027-06"),
    ("project", "资料检索助手", "name", "资料检索助手"),
    ("project", "资料检索助手", "start_date", "2026-03"),
    ("project", "资料检索助手", "end_date", "2026-08"),
    ("project", "资料检索助手", "role", "独立开发者"),
    ("project", "资料检索助手", "tool", "Python、RAG"),
    ("project", "资料检索助手", "status", "本地演示原型"),
    ("project", "资料检索助手", "description", "开发文档检索与引用核对功能"),
    ("project", "资料检索助手", "result", "用40条自建问题离线检查引用是否匹配"),
    ("project", "任务编排器", "name", "任务编排器"),
    ("project", "任务编排器", "start_date", "2026-06"),
    ("project", "任务编排器", "end_date", "至今"),
    ("project", "任务编排器", "role", "独立开发者"),
    ("project", "任务编排器", "tool", "Python、Agent 工具调用"),
    ("project", "任务编排器", "status", "本地演示原型"),
    ("project", "任务编排器", "description", "开发任务重试与结果核对功能"),
    ("campus", "读书社", "name", "读书社"),
    ("campus", "读书社", "description", "协助登记借阅记录"),
]
PROJECTS = ("资料检索助手", "任务编排器")


def seed(db, account):
    from app.services.profile_service import add_fact
    for category, subject, field, value in FACTS:
        add_fact(db, account, category=category, subject=subject, field=field, value=value)


def start(client, database):
    """只新建随机合成账号；不读取/修改已有账号，凭证仅在 cookie jar 中。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import get_settings
    from app.services.account_service import blind_index, ACCOUNT_COOKIE
    from app.services.data_crypto import get_crypto
    from app.models.account import Account, AccountSession
    if not database or get_settings().APP_ENV == "production":
        raise ValueError("returning requires an explicit local replay database")
    path = Path(database).resolve()
    if not path.is_file():
        raise ValueError("Replay database must already exist")
    engine = create_engine("sqlite:///" + str(path))
    account, token = str(uuid4()), secrets.token_urlsafe(32)
    email = "returning-" + account + "@example.invalid"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with Session(engine) as db:
            db.add(Account(id=account, email_index=blind_index(email, scope="email"),
                email_ciphertext=get_crypto().encrypt_text(email, owner="account:" + account, record=account, field="email")))
            db.add(AccountSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=account,
                                  created_at=now, expires_at=now + timedelta(hours=2)))
            seed(db, account)
            db.commit()
        host = urlsplit(client.base).hostname
        client.cookies.set_cookie(Cookie(0, ACCOUNT_COOKIE, token, None, False, host, False, False,
            "/", True, client.base.startswith("https:"), None, True, None, None, {"HttpOnly": None}, False))
        client.session_id = client.json("/api/chat/conversations", {})["session_id"]
        # 核对服务确实读取同一个数据库与账号；错库时不启动付费聊天。
        profile = client.json("/api/profile")
        if not any(f.get("value") == PROJECTS[0] for f in profile.get("facts", [])):
            raise ValueError("Returning profile was not loaded by the service")
    finally:
        engine.dispose()


def replay(client):
    turn = client.turn("initial", FIRST)
    yield turn
    if turn.get("status") != "ok":
        return
    turn = client.turn("select", "我想投" + ROLE + "，请从档案选相关经历导入当前简历。")
    yield turn
    if turn.get("status") != "ok":
        return
    turn = client.turn("draft", "按现有材料生成简历草稿。")  # 与界面「生成草稿」按钮的发送值一致
    yield turn
    guidance = (turn.get("workspace") or {}).get("guidance") or {}
    if turn.get("status") == "ok" and guidance.get("kind") == "structure_plan":
        option = next(o["value"] for o in guidance.get("options", []) if o.get("label") == "按推荐写")
        yield client.turn("confirm", option, kind="confirmation", trigger_action="draft")


def import_receipt(turn):
    checks = import_module("evaluation.persona-ux.checks")
    reply = turn.get("reply", "")
    names = {p.get("name") for p in checks.visible_items(turn.get("resume_data") or {}, "projects")}
    if not all(name in reply and name in names for name in PROJECTS):
        return False
    action = r"(?:导入|采用|选用|选进|写入)"
    completed = re.compile(r"(?:已|已经).{0,30}" + action
        + r"|选进了(?:稿子|简历)|(?:导入|采用|写入)了|导入的|从档案选了")
    incomplete = re.compile(r"[？?]|(?:未|没有|没能|将|会|准备|打算|可以|建议|是否|要不要).{0,12}"
        + action + "|" + action + r".{0,12}(?:失败|未完成)")
    adopted = set()
    blocks = re.split(r"\n\s*\n", reply)
    # 「…导入了两段：」与其后的列表之间常隔一个空行，视为同一段落再判定。
    merged = []
    for block in blocks:
        lines = block.strip().splitlines()
        if (merged and lines and all(re.match(r"\s*(?:[-*]|\d+[.)、])\s", line) for line in lines)
                and re.search(r"[：:]\s*$", merged[-1]) and "\n" not in merged[-1].strip()):
            merged[-1] = merged[-1].rstrip() + "\n" + block.strip()
        else:
            merged.append(block)
    for block in merged:
        lines = block.strip().splitlines()
        # A completed-action heading governs its immediately following named list.
        if (len(lines) > 1 and completed.search(lines[0]) and not incomplete.search(lines[0])
                and all(re.match(r"\s*(?:[-*]|\d+[.)、])\s", line) for line in lines[1:])):
            clauses = [block]
        else:
            clauses = re.split(r"(?<=[。！!？?；;])|\n", block)
        for clause in clauses:
            if completed.search(clause) and not incomplete.search(clause):
                adopted.update(name for name in PROJECTS if name in clause)
    return set(PROJECTS) <= adopted


def evaluate_persona(persona, turns, **_):
    checks = import_module("evaluation.persona-ux.checks")
    first = turns[0] if turns else {}
    final = turns[-1] if turns else {}
    body = str(final.get("resume_data") or {})
    cases = [
        ("common.rounds_complete", len(turns) >= 3 and all(t.get("status") == "ok" and t.get("sse_done") for t in turns), "status", "至少三轮且 SSE 完整"),
        ("profile.no_basics_form", ((first.get("workspace") or {}).get("guidance") or {}).get("kind") != "intake_basics", "workspace", "已有档案不重填基本信息"),
        ("profile.no_false_unrecorded", all("没记下来" not in t.get("reply", "") for t in turns), "reply", "正常档案请求不误报遗漏"),
        ("profile.import_receipt", any(import_receipt(t) for t in turns), "reply", "完成选用回执点名两段经历，且同轮可见数据包含它们"),
        ("profile.draft", all(n in body for n in PROJECTS) and final.get("stage") in {"EVALUATING", "EXPORT"}, "resume_data", "生成稿含档案经历"),
        ("profile.contacts", all(v in body for c, _, f, v in FACTS if c == "basic" and f in {"phone", "email"}), "resume_data", "头部带上联系方式"),
    ]
    return [{"id": persona + "." + identifier, "status": "pass" if ok else "fail", "title": title,
             "evidence": ([checks.evidence(t, path, t.get('reply', '')) for t in turns
                           if import_receipt(t)] or [checks.evidence(final, path, final.get('reply', ''))])
             if identifier == 'profile.import_receipt' else [checks.evidence(final, path, title)]}
            for identifier, ok, path, title in cases]
