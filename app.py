from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from connectors import CONNECTORS

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "radar.db"
PROFILE_PATH = ROOT / "config" / "profile.json"

DEFAULT_PROFILE = {
    "graduation": "2027-11",
    "school": "Your university",
    "availability_start": "2026-12-01",
    "availability_end": "2027-02-17",
    "days_per_week": 5,
    "priority_cities": ["上海", "杭州", "苏州", "南京", "宁波"],
    "secondary_cities": ["深圳", "广州", "珠海", "厦门"],
    "role_priority": ["后端开发", "AI应用", "平台研发", "云原生", "数据工程", "全栈开发", "测试开发"],
    "skills": ["Java", "Spring Boot", "Python", "SQL", "Redis", "Linux", "Docker", "Git"],
}


def load_profile() -> dict[str, Any]:
    """Load a local-only profile, falling back to a safe public example."""
    if not PROFILE_PATH.exists():
        return DEFAULT_PROFILE.copy()
    with PROFILE_PATH.open(encoding="utf-8") as profile_file:
        saved_profile = json.load(profile_file)
    return {**DEFAULT_PROFILE, **saved_profile}


PROFILE = load_profile()

# All links point to official career portals. "planned" means the connector is intentionally
# not active until its public data contract has been validated and a low-frequency adapter exists.
COMPANIES = [
    ("字节跳动", "https://jobs.bytedance.com/campus/", "active", "公开校园实习 API（单次最多 100 条）"),
    ("腾讯", "https://join.qq.com/", "active", "公开校园实习 API（动态读取招聘项目）"),
    ("美团", "https://zhaopin.meituan.com/web/campus", "active", "公开实习职位 API（单次最多 100 条）"),
    ("百度", "https://talent.baidu.com/jobs/", "active", "公开日常实习 API（单次最多 20 条）"),
    ("阿里巴巴", "https://talent.alibaba.com/", "planned", "官网职位页"),
    ("蚂蚁集团", "https://talent.antgroup.com/", "planned", "官网职位页"),
    ("京东", "https://campus.jd.com/", "active", "公开实习职位 API（单次最多 100 条）"),
    ("快手", "https://zhaopin.kuaishou.cn/", "planned", "官网职位页"),
    ("小红书", "https://job.xiaohongshu.com/", "active", "公开校园职位 API（含实习项目）"),
    ("滴滴", "https://talent.didiglobal.com/", "active", "公开校园/实习职位 API（6 页上限）"),
    ("网易", "https://hr.163.com/job-list.html?workType=1", "active", "公开校园/实习职位 API（单次最多 100 条）"),
    ("哔哩哔哩", "https://jobs.bilibili.com/", "active", "公开实习职位 API（匿名 CSRF 握手）"),
    ("米哈游", "https://jobs.mihoyo.com/", "planned", "官方职位接口"),
    ("大疆", "https://we.dji.com/zh-CN", "planned", "官网职位页"),
    ("携程", "https://careers.ctrip.com/campus", "active", "公开职位 API（实习岗位客户端过滤）"),
    ("科大讯飞", "https://iflytek.zhiye.com/jobs", "active", "公开飞YOUNG实习生 API（当前可能无开放岗位）"),
    ("商汤科技", "https://hr.sensetime.com/edu", "planned", "官网接口当前不稳定，等待重新验证"),
    ("金山办公", "https://talent.wps.cn/", "planned", "官网职位页"),
    ("地平线", "https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/school.html", "active", "公开校园/实习职位 API"),
    ("小鹏汽车", "https://xiaopeng.jobs.feishu.cn/campus", "active", "公开校园实习 API"),
    ("蔚来", "https://nio.jobs.feishu.cn/campus", "active", "公开校园实习 API"),
    ("理想汽车", "https://www.lixiang.com/employ/campus.html", "planned", "官网职位页，待验证公开接口"),
    ("极氪", "https://www.zeekrlife.com/career", "planned", "官网职位页，待验证公开接口"),
    ("海康威视", "https://hr.hikvision.com/", "planned", "官网存在访问限制，待验证公开接口"),
    ("微众银行", "https://www.webank.com/career/", "planned", "招聘主要通过公众号/小程序，暂无公开 API"),
    ("平安科技", "https://campus.pingan.com/", "planned", "官网职位页，待验证公开接口"),
]

app = FastAPI(title="国内实习雷达")


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(connection()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL, company TEXT NOT NULL, city TEXT DEFAULT '',
          description TEXT DEFAULT '', url TEXT NOT NULL UNIQUE, source TEXT DEFAULT '官网',
          posted_at TEXT DEFAULT '', duration_weeks INTEGER, work_days INTEGER,
          score INTEGER NOT NULL DEFAULT 0, score_reasons TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT '待浏览', favorite INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS companies (
          name TEXT PRIMARY KEY, careers_url TEXT NOT NULL, status TEXT NOT NULL,
          connector_note TEXT NOT NULL, last_checked_at TEXT, last_result TEXT
        );
        """)
        conn.executemany(
            """INSERT INTO companies(name, careers_url, status, connector_note) VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET careers_url=excluded.careers_url,
              status=excluded.status, connector_note=excluded.connector_note""",
            COMPANIES,
        )
        conn.commit()


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def score_job(job: dict[str, Any]) -> tuple[int, list[str]]:
    text = normalized(" ".join(str(job.get(k) or "") for k in ("title", "description", "city")))
    score, reasons = 0, []
    role_rules = [
        ("后端开发", ["后端", "服务端", "java", "spring", "golang", "go开发"], 35),
        ("AI应用", ["ai应用", "大模型", "llm", "rag", "智能体", "生成式ai"], 32),
        ("平台研发", ["平台研发", "基础架构", "中间件", "分布式"], 30),
        ("云原生", ["云原生", "kubernetes", "k8s", "devops", "sre"], 27),
        ("数据工程", ["数据工程", "数据开发", "数据平台", "etl"], 25),
        ("全栈开发", ["全栈", "fullstack"], 20),
        ("测试开发", ["测试开发", "测试工程"], 18),
    ]
    best = max(((points, name) for name, words, points in role_rules if any(w in text for w in words)), default=(0, ""))
    if best[0]:
        score += best[0]
        reasons.append(f"方向匹配：{best[1]} +{best[0]}")

    skill_words = ["java", "spring", "python", "sql", "mysql", "redis", "linux", "docker", "kubernetes", "git", "typescript", "react"]
    hits = sorted({word for word in skill_words if word in text})
    skill_points = min(25, len(hits) * 4)
    if skill_points:
        score += skill_points
        reasons.append(f"技能交集：{'、'.join(hits)} +{skill_points}")

    city = str(job.get("city") or "")
    if any(c in city for c in PROFILE["priority_cities"]):
        score += 15; reasons.append("长三角优先城市 +15")
    elif any(c in city for c in PROFILE["secondary_cities"]):
        score += 10; reasons.append("珠三角次优城市 +10")

    duration = job.get("duration_weeks")
    days = job.get("work_days")
    if duration is None or int(duration) <= 10:
        score += 10; reasons.append("可匹配 10 周窗口 +10")
    else:
        reasons.append("实习时长可能超过可用窗口 +0")
    if days is None or int(days) <= 5:
        score += 10; reasons.append("到岗频率可匹配 +10")

    if any(x in text for x in ["在校", "实习", "intern"]):
        score += 5; reasons.append("面向在校实习生 +5")
    return min(100, score), reasons


class JobInput(BaseModel):
    title: str
    company: str
    city: str = ""
    description: str = ""
    url: str
    source: str = "官网"
    posted_at: str = ""
    duration_weeks: int | None = None
    work_days: int | None = None


class JobUpdate(BaseModel):
    status: str | None = None
    favorite: bool | None = None


class SyncRequest(BaseModel):
    sources: list[str] | None = None


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/static/{filename}", include_in_schema=False)
def static(filename: str) -> FileResponse:
    return FileResponse(ROOT / "static" / filename)


@app.get("/api/profile")
def profile() -> dict[str, Any]:
    return PROFILE


@app.get("/api/jobs")
def list_jobs(q: str = "", status: str = "", city_group: str = "") -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY favorite DESC, score DESC, updated_at DESC")]
    for row in rows:
        row["favorite"] = bool(row["favorite"])
        row["score_reasons"] = json.loads(row["score_reasons"])
    term = normalized(q)
    if term:
        rows = [r for r in rows if term in normalized(" ".join(str(r[k]) for k in ("title", "company", "city", "description")))]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if city_group == "yangtze":
        rows = [r for r in rows if any(c in r["city"] for c in PROFILE["priority_cities"])]
    if city_group == "pearl":
        rows = [r for r in rows if any(c in r["city"] for c in PROFILE["secondary_cities"])]
    return rows


@app.post("/api/jobs")
def upsert_job(job: JobInput) -> dict[str, Any]:
    raw = job.model_dump()
    score, reasons = score_job(raw)
    now = datetime.now(timezone.utc).isoformat()
    values = {**raw, "score": score, "score_reasons": json.dumps(reasons, ensure_ascii=False), "updated_at": now}
    with closing(connection()) as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE url = ?", (raw["url"],)).fetchone()
        if existing:
            conn.execute("""UPDATE jobs SET title=:title, company=:company, city=:city, description=:description,
                source=:source, posted_at=:posted_at, duration_weeks=:duration_weeks, work_days=:work_days,
                score=:score, score_reasons=:score_reasons, updated_at=:updated_at WHERE url=:url""", values)
            job_id = existing["id"]
        else:
            conn.execute("""INSERT INTO jobs(title,company,city,description,url,source,posted_at,duration_weeks,work_days,
                score,score_reasons,created_at,updated_at) VALUES (:title,:company,:city,:description,:url,:source,:posted_at,
                :duration_weeks,:work_days,:score,:score_reasons,:updated_at,:updated_at)""", values)
            job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    return {"id": job_id, "score": score, "reasons": reasons}


@app.post("/api/jobs/import")
def import_jobs(jobs: list[JobInput]) -> dict[str, int]:
    for job in jobs:
        upsert_job(job)
    return {"imported": len(jobs)}


@app.post("/api/sync")
def sync_jobs(request: SyncRequest) -> dict[str, Any]:
    """Sync public APIs with a per-company 20-minute safety window."""
    selected = request.sources or list(CONNECTORS)
    unknown = sorted(set(selected) - set(CONNECTORS))
    if unknown:
        raise HTTPException(400, f"暂不支持的数据源：{'、'.join(unknown)}")
    now = datetime.now(timezone.utc)
    results = []
    for company in selected:
        with closing(connection()) as conn:
            row = conn.execute("SELECT last_checked_at FROM companies WHERE name = ?", (company,)).fetchone()
        if row and row["last_checked_at"]:
            previous = datetime.fromisoformat(row["last_checked_at"])
            if now - previous < timedelta(minutes=20):
                wait_seconds = int((timedelta(minutes=20) - (now - previous)).total_seconds())
                results.append({"company": company, "status": "skipped", "message": f"低频保护：请在约 {max(1, wait_seconds // 60)} 分钟后再同步"})
                continue
        try:
            fetched = CONNECTORS[company]()
            for raw_job in fetched.jobs:
                upsert_job(JobInput(**raw_job))
            message, status = f"{fetched.message}；已写入/更新 {len(fetched.jobs)} 条", "ok"
        except Exception as error:
            message, status = f"同步失败：{error}", "error"
        with closing(connection()) as conn:
            conn.execute("UPDATE companies SET last_checked_at = ?, last_result = ? WHERE name = ?", (now.isoformat(), message, company))
            conn.commit()
        results.append({"company": company, "status": status, "message": message})
    return {"results": results}


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, update: JobUpdate) -> dict[str, bool]:
    allowed = {"待浏览", "已收藏", "已投递", "面试中", "已拒绝", "已录用"}
    if update.status is not None and update.status not in allowed:
        raise HTTPException(400, "未知状态")
    fields, params = [], []
    if update.status is not None: fields += ["status = ?"]; params += [update.status]
    if update.favorite is not None: fields += ["favorite = ?"]; params += [int(update.favorite)]
    if not fields: return {"ok": True}
    fields += ["updated_at = ?"]; params += [datetime.now(timezone.utc).isoformat(), job_id]
    with closing(connection()) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int) -> dict[str, bool]:
    """Remove a manually entered or imported listing that was added in error."""
    with closing(connection()) as conn:
        result = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "职位不存在")
    return {"ok": True}


@app.get("/api/companies")
def companies() -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM companies ORDER BY name")]


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with closing(connection()) as conn:
        summary = conn.execute("""SELECT COUNT(*) total, SUM(score >= 75) strong,
          SUM(status = '已投递') applied, SUM(status = '面试中') interviewing FROM jobs""").fetchone()
        companies_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    return {"total": summary["total"], "strong": summary["strong"] or 0, "applied": summary["applied"] or 0,
            "interviewing": summary["interviewing"] or 0, "companies": companies_count}


@app.get("/api/jobs/export")
def export_jobs() -> Response:
    jobs = list_jobs()
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(["评分", "职位", "公司", "城市", "来源", "状态", "链接", "评分原因"])
    for j in jobs:
        writer.writerow([j["score"], j["title"], j["company"], j["city"], j["source"], j["status"], j["url"], "；".join(j["score_reasons"])])
    return Response("\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=internship-radar.csv"})
