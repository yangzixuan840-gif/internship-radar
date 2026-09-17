"""Low-frequency local worker for official job-source polling.

Run it alongside the web server. It only calls already verified public
connectors and relies on the API's per-company cooldown for safety.
"""

from __future__ import annotations

import time

from app import PROFILE, SyncRequest, init_db, sync_jobs


def main() -> None:
    init_db()
    interval = max(20, int(PROFILE.get("sync_minutes", 30))) * 60
    while True:
        result = sync_jobs(SyncRequest())
        ok = sum(item["status"] == "ok" for item in result["results"])
        print(f"同步轮次完成：{ok}/{len(result['results'])} 个来源成功；{interval // 60} 分钟后重试", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
