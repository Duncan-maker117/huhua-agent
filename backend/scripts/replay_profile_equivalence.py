"""只读评估数据库副本，仅输出计数；解密配置从应用环境注入，不加载 .env。"""

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.data_crypto import crypto_from_settings
from app.services.profile_equivalence import equivalent_value, split_skill_values


CATEGORIES = {"basic", "education", "project", "work", "open_source", "awards", "skill", "preference"}
FIELDS = {"name", "phone", "email", "location", "objective", "school", "degree", "major",
          "start_date", "end_date", "company", "title", "role", "status", "description", "result",
          "skill", "preference", "tool", "deliverable", "summary", "pr", "level", "date",
          "highlights", "link", "github", "website", "availability"}
RESULTS = ("same", "new_more_specific", "old_more_specific", "different")


def replay(db_path, crypto):
    def unpack(row):
        return json.loads(crypto.decrypt_text(row["payload"], owner=f"account:{row['account_id']}",
                                             record=row["id"], field="payload"))

    counts = {"pending_total": 0, "equivalence": dict.fromkeys(RESULTS, 0), "by_category_field": {},
              "skill_facts_total": 0, "skill_facts_active": 0, "skill_bundles": 0,
              "skill_bundle_expected_items": 0, "skill_expected_items": 0}
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute("SELECT * FROM profile_conflicts WHERE status = 'pending'"):
            counts["pending_total"] += 1
            data = unpack(row)
            fact = db.execute("SELECT * FROM profile_facts WHERE id = ? AND account_id = ?",
                              (row["fact_id"], row["account_id"])).fetchone()
            category = fact["category"] if fact else "other"
            field = unpack(fact).get("field", "") if fact else data.get("field", "")
            outcome = equivalent_value(category, field, data.get("current_value", ""), data.get("proposed_value", ""))
            counts["equivalence"][outcome] += 1
            # 未知字段归 other，避免将被污染的字段名当作统计标签泄漏。
            label = (category if category in CATEGORIES else "other") + "/" + (field if field in FIELDS else "other")
            bucket = counts["by_category_field"].setdefault(label, dict.fromkeys(RESULTS, 0))
            bucket[outcome] += 1
        statuses = Counter()
        for row in db.execute("SELECT * FROM profile_facts WHERE category = 'skill'"):
            value = unpack(row).get("value", "")
            items = split_skill_values(value)
            counts["skill_facts_total"] += 1
            counts["skill_expected_items"] += len(items)
            status = row["status"] if row["status"] in {"active", "deleted", "superseded"} else "other"
            statuses[status] += 1
            if row["status"] == "active":
                counts["skill_facts_active"] += 1
            if len(split_skill_values(value, deduplicate=False)) > 1:
                counts["skill_bundles"] += 1
                counts["skill_bundle_expected_items"] += len(items)
        counts["skill_by_status"] = dict(statuses)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path")
    args = parser.parse_args(argv)
    try:
        from app.config import Settings
        counts = replay(args.db_path, crypto_from_settings(Settings(_env_file=None)))
    except Exception:
        # 不打印异常、路径、密文或事实正文；失败也只输出计数。
        print(json.dumps({"errors": 1}))
        return 1
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
