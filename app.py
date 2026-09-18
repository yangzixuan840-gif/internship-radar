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

from fastapi import Body, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from connectors import CONNECTORS
from notifier import send_markdown, webhook_url

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "radar.db"
RESUMES_PATH = ROOT / "data" / "resumes"
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
    "alert_threshold": 75,
    "sync_minutes": 30,
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
    ("华为", "https://career.huawei.com/reccampportal/portal5/index.html", "planned", "官方校园招聘入口，待验证低频公开接口"),
    ("小米", "https://xiaomi.jobs.f.mioffice.cn/campus", "planned", "官方校园招聘入口，待验证低频公开接口"),
    ("途虎养车", "https://tuhu.jobs.feishu.cn/", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("拼多多", "https://careers.pinduoduo.com/", "planned", "官方校园招聘入口，待验证低频公开接口"),
    ("OPPO", "https://careers.oppo.com/", "planned", "官方校园招聘入口，待验证低频公开接口"),
    ("vivo", "https://hr-campus.vivo.com/", "planned", "官方校园及实习招聘入口，待验证低频公开接口"),
    ("新浪微博", "https://app.mokahr.com/campus_apply/sina", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("爱奇艺", "https://iqiyi.jobs.feishu.cn/", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("得物", "https://join.dewu.com/", "planned", "官方招聘入口，待验证低频公开接口"),
    ("顺丰科技", "https://hr.sf-express.com/", "planned", "官方招聘入口，待验证低频公开接口"),
    ("菜鸟", "https://campus.cainiao.com/", "planned", "官方招聘入口，待验证低频公开接口"),
    ("同程旅行", "https://hr.ly.com/", "planned", "官方招聘入口，待验证低频公开接口"),
    ("DeepSeek", "https://jobs.mokahr.com/campus-recruitment/deepseek", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("月之暗面", "https://app.mokahr.com/campus-recruitment/moonshot", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("智谱 AI", "https://zhipu-ai.jobs.feishu.cn/", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("MiniMax", "https://vrfi1sk8a0.jobs.feishu.cn/", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("阶跃星辰", "https://app.mokahr.com/campus-recruitment/stepfun", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("百川智能", "https://baichuanai.jobs.feishu.cn/", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("寒武纪", "https://app.mokahr.com/campus-recruitment/cambricon", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("旷视科技", "https://app.mokahr.com/campus-recruitment/megvii", "planned", "官方招聘系统入口，待验证低频公开接口"),
    ("荣耀", "https://career.hihonor.com/", "planned", "AI 终端与系统研发，官方招聘入口"),
    ("联想", "https://jobs.lenovo.com/", "planned", "终端、云与企业服务，官方招聘入口"),
    ("中兴通讯", "https://job.zte.com.cn/", "planned", "通信与算力基础设施，官方招聘入口"),
    ("360", "https://hr.360.cn/", "planned", "安全与 AI 产品，官方招聘入口"),
    ("海尔智家", "https://zhaopin.haier.net/", "planned", "智能制造与 IoT，官方招聘入口"),
    ("美的集团", "https://zhaopin.midea.com/", "planned", "智能制造与机器人，官方招聘入口"),
    ("TCL 科技", "https://zhaopin.tcl.com/", "planned", "显示、半导体与智能终端，官方招聘入口"),
    ("比亚迪", "https://job.byd.com/", "planned", "新能源汽车与智能制造，官方招聘入口"),
    ("吉利汽车", "https://zhaopin.geely.com/", "planned", "智能汽车与软件，官方招聘入口"),
    ("长城汽车", "https://zhaopin.gwm.cn/", "planned", "智能汽车与智能制造，官方招聘入口"),
    ("上汽集团", "https://job.saicmotor.com/", "planned", "智能网联汽车，官方招聘入口"),
    ("宇树科技", "https://www.unitree.com/career", "planned", "机器人与具身智能，官方招聘入口"),
    ("智元机器人", "https://www.zhiyuanrobot.com/career", "planned", "具身智能与机器人，官方招聘入口"),
    ("星尘智能", "https://www.astribot.com/careers/", "planned", "具身智能，官方招聘页含实习岗位"),
    ("星猿哲科技", "https://xyzrobotics.jobs.feishu.cn/2026/", "planned", "机器人算法与工程，官方招聘入口"),
    ("千寻智能", "https://nwd4iy9rd2s.jobs.feishu.cn/campusofSpiritAI", "planned", "具身智能，官方校园招聘入口"),
    ("文远知行", "https://www.weride.ai/career", "planned", "自动驾驶与通用 AI，官方招聘入口"),
    ("小马智行", "https://careers.pony.ai/", "planned", "自动驾驶与平台研发，官方招聘入口"),
    ("Momenta", "https://www.momenta.cn/career", "planned", "自动驾驶与数据闭环，官方招聘入口"),
    ("普渡科技", "https://www.pudurobotics.com/career", "planned", "服务机器人，官方招聘入口"),
    ("云深处科技", "https://www.deeprobotics.cn/career", "planned", "四足机器人与控制，官方招聘入口"),
    ("第四范式", "https://www.4paradigm.com/career", "planned", "企业级 AI 平台，官方招聘入口"),
    ("云从科技", "https://www.cloudwalk.com/career", "planned", "计算机视觉与 AI 平台，官方招聘入口"),
    ("金蝶", "https://zhaopin.kingdee.com/", "planned", "企业 SaaS 与云原生，官方招聘入口"),
    ("用友", "https://career.yonyou.com/", "planned", "企业软件与数据平台，官方招聘入口"),
    ("浪潮", "https://zhaopin.inspur.com/", "planned", "服务器、云与数据中心，官方招聘入口"),
    ("深信服", "https://career.sangfor.com.cn/", "planned", "云、安全与平台研发，官方招聘入口"),
    ("奇安信", "https://jobs.qianxin.com/", "planned", "网络安全与工程平台，官方招聘入口"),
    ("新华三", "https://job.h3c.com/", "planned", "网络、云与 AI 基础设施，官方招聘入口"),
]

app = FastAPI(title="国内实习雷达")


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
        CREATE TABLE IF NOT EXISTS source_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
          started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
          fetched_count INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT '待发送', created_at TEXT NOT NULL,
          handled_at TEXT, FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, created_at DESC);
        CREATE TABLE IF NOT EXISTS resumes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
          filename TEXT DEFAULT '', mime_type TEXT DEFAULT '', stored_path TEXT DEFAULT '',
          summary TEXT NOT NULL DEFAULT '', skills TEXT NOT NULL DEFAULT '[]',
          is_default INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS application_kits (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, resume_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT '待确认', kit_json TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(job_id, resume_id), FOREIGN KEY(job_id) REFERENCES jobs(id),
          FOREIGN KEY(resume_id) REFERENCES resumes(id)
        );
        CREATE INDEX IF NOT EXISTS idx_application_kits_status ON application_kits(status, updated_at DESC);
        """)
        alert_columns = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)")}
        if "last_error" not in alert_columns:
            conn.execute("ALTER TABLE alerts ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")
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


class AlertUpdate(BaseModel):
    status: str


class ResumeInput(BaseModel):
    name: str
    summary: str = ""
    skills: list[str] = []
    is_default: bool = False


class ApplicationKitUpdate(BaseModel):
    status: str


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
def list_jobs(q: str = "", status: str = "", city_group: str = "", company: str = "") -> list[dict[str, Any]]:
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
    if company:
        rows = [r for r in rows if r["company"] == company]
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
    created = False
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
            created = True
        conn.commit()
    return {"id": job_id, "score": score, "reasons": reasons, "created": created}


def queue_alert_if_relevant(job: dict[str, Any]) -> bool:
    """Create exactly one local notification-outbox item for a new strong match."""
    if not job["created"] or job["score"] < int(PROFILE["alert_threshold"]):
        return False
    now = datetime.now(timezone.utc).isoformat()
    with closing(connection()) as conn:
        conn.execute("INSERT OR IGNORE INTO alerts(job_id, created_at) VALUES (?, ?)", (job["id"], now))
        queued = conn.execute("SELECT changes()").fetchone()[0] == 1
        conn.commit()
    return queued


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned[:120] or "resume.bin"


def build_application_kit(job: sqlite3.Row, resume: sqlite3.Row) -> dict[str, Any]:
    resume_skills = [str(skill) for skill in json.loads(resume["skills"])]
    job_text = normalized(" ".join(str(job[key] or "") for key in ("title", "description", "city")))
    hits = [skill for skill in resume_skills if normalized(skill) and normalized(skill) in job_text]
    role_terms = ["Python", "Java", "SQL", "Docker", "Redis", "Spring", "React", "Linux", "Kubernetes", "LLM", "RAG"]
    gaps = [term for term in role_terms if normalized(term) in job_text and term not in hits]
    return {
        "resume_name": resume["name"], "job_score": job["score"], "matched_skills": hits,
        "possible_gaps": gaps,
        "checklist": [
            "核对毕业时间、到岗日期和每周到岗天数是否符合岗位要求。",
            "只保留简历中真实存在的项目、技能和成果，不补造经历。",
            "在招聘官网确认职位仍开放，并手动检查隐私声明与投递问题。",
        ],
        "cover_letter_draft": f"您好，我对 {job['company']} 的 {job['title']} 职位很感兴趣。我的经历与技能概览已随简历提交；我愿意根据岗位要求进一步说明相关项目实践。期待有机会交流，谢谢。",
    }


def dispatch_wecom_alerts(limit: int = 8) -> dict[str, Any]:
    """Send one digest and atomically mark only its included alerts as sent."""
    if not webhook_url():
        return {"sent": 0, "status": "not_configured", "message": "未配置企业微信机器人 Webhook，提醒保留在待发送队列"}
    with closing(connection()) as conn:
        alerts = [dict(row) for row in conn.execute("""
          SELECT a.id, j.title, j.company, j.city, j.url, j.score
          FROM alerts a JOIN jobs j ON j.id = a.job_id
          WHERE a.status = '待发送' ORDER BY j.score DESC, a.created_at ASC LIMIT ?
        """, (limit,))]
    if not alerts:
        return {"sent": 0, "status": "empty", "message": "没有待发送提醒"}
    lines = ["## 实习雷达：发现高匹配新岗位"]
    for item in alerts:
        location = item["city"] or "地点待确认"
        lines.append(f"> **{item['company']} · {item['title']}**（{item['score']} 分）\\n> {location}\\n> {item['url']}")
    try:
        send_markdown("\n\n".join(lines))
    except Exception as error:
        with closing(connection()) as conn:
            conn.executemany("UPDATE alerts SET last_error = ? WHERE id = ?", [(str(error), item["id"]) for item in alerts])
            conn.commit()
        return {"sent": 0, "status": "error", "message": f"企业微信发送失败：{error}"}
    now = datetime.now(timezone.utc).isoformat()
    with closing(connection()) as conn:
        conn.executemany("UPDATE alerts SET status = '已发送', handled_at = ?, last_error = '' WHERE id = ?", [(now, item["id"]) for item in alerts])
        conn.commit()
    return {"sent": len(alerts), "status": "ok", "message": f"已推送 {len(alerts)} 条企业微信提醒"}


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
        with closing(connection()) as conn:
            run_id = conn.execute("INSERT INTO source_runs(company, started_at, status) VALUES (?, ?, 'running')", (company, now.isoformat())).lastrowid
            conn.commit()
        try:
            fetched = CONNECTORS[company]()
            alerts_queued = 0
            for raw_job in fetched.jobs:
                saved = upsert_job(JobInput(**raw_job))
                alerts_queued += int(queue_alert_if_relevant(saved))
            message, status = f"{fetched.message}；已写入/更新 {len(fetched.jobs)} 条；新增待提醒 {alerts_queued} 条", "ok"
        except Exception as error:
            fetched, message, status = None, f"同步失败：{error}", "error"
        with closing(connection()) as conn:
            conn.execute("UPDATE companies SET last_checked_at = ?, last_result = ? WHERE name = ?", (now.isoformat(), message, company))
            conn.execute("UPDATE source_runs SET finished_at = ?, status = ?, fetched_count = ?, message = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), status, len(fetched.jobs) if fetched else 0, message, run_id))
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


@app.get("/api/resumes")
def list_resumes() -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM resumes ORDER BY is_default DESC, updated_at DESC")]
    for row in rows:
        row["is_default"] = bool(row["is_default"])
        row["skills"] = json.loads(row["skills"])
        row["has_file"] = bool(row.pop("stored_path"))
    return rows


@app.post("/api/resumes")
def upsert_resume(resume: ResumeInput) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with closing(connection()) as conn:
        if resume.is_default:
            conn.execute("UPDATE resumes SET is_default = 0")
        existing = conn.execute("SELECT id FROM resumes WHERE name = ?", (resume.name,)).fetchone()
        values = (resume.summary, json.dumps(resume.skills, ensure_ascii=False), int(resume.is_default), now, resume.name)
        if existing:
            conn.execute("UPDATE resumes SET summary = ?, skills = ?, is_default = ?, updated_at = ? WHERE name = ?", values)
            resume_id = existing["id"]
        else:
            conn.execute("INSERT INTO resumes(name, summary, skills, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (resume.name, resume.summary, json.dumps(resume.skills, ensure_ascii=False), int(resume.is_default), now, now))
            resume_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    return {"id": resume_id}


@app.put("/api/resumes/{resume_id}/file")
def upload_resume_file(resume_id: int, content: bytes = Body(...), filename: str = Header("resume.pdf")) -> dict[str, Any]:
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "简历文件必须在 1 到 10MB 之间")
    name = safe_filename(filename)
    RESUMES_PATH.mkdir(parents=True, exist_ok=True)
    with closing(connection()) as conn:
        if not conn.execute("SELECT id FROM resumes WHERE id = ?", (resume_id,)).fetchone():
            raise HTTPException(404, "简历版本不存在")
        target = RESUMES_PATH / f"{resume_id}_{name}"
        target.write_bytes(content)
        stored_path = str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target)
        conn.execute("UPDATE resumes SET filename = ?, stored_path = ?, mime_type = ?, updated_at = ? WHERE id = ?", (name, stored_path, "application/octet-stream", datetime.now(timezone.utc).isoformat(), resume_id))
        conn.commit()
    return {"ok": True, "filename": name}


@app.post("/api/jobs/{job_id}/application-kit")
def create_application_kit(job_id: int, resume_id: int | None = None) -> dict[str, Any]:
    with closing(connection()) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "职位不存在")
        resume = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone() if resume_id else conn.execute("SELECT * FROM resumes WHERE is_default = 1 ORDER BY updated_at DESC LIMIT 1").fetchone()
        if not resume:
            raise HTTPException(400, "请先创建并设为默认简历版本")
        kit = build_application_kit(job, resume)
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute("SELECT id FROM application_kits WHERE job_id = ? AND resume_id = ?", (job_id, resume["id"])).fetchone()
        if existing:
            conn.execute("UPDATE application_kits SET kit_json = ?, status = '待确认', updated_at = ? WHERE id = ?", (json.dumps(kit, ensure_ascii=False), now, existing["id"]))
            kit_id = existing["id"]
        else:
            conn.execute("INSERT INTO application_kits(job_id, resume_id, kit_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (job_id, resume["id"], json.dumps(kit, ensure_ascii=False), now, now))
            kit_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    return {"id": kit_id, "status": "待确认", "kit": kit}


@app.get("/api/application-kits")
def list_application_kits(status: str = "") -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        rows = [dict(row) for row in conn.execute("""
          SELECT k.id, k.status, k.created_at, k.updated_at, k.kit_json,
                 j.title, j.company, j.city, j.url, j.score, r.name AS resume_name, r.filename
          FROM application_kits k JOIN jobs j ON j.id = k.job_id JOIN resumes r ON r.id = k.resume_id
          WHERE (? = '' OR k.status = ?) ORDER BY k.updated_at DESC
        """, (status, status))]
    for row in rows:
        row["kit"] = json.loads(row.pop("kit_json"))
    return rows


@app.patch("/api/application-kits/{kit_id}")
def update_application_kit(kit_id: int, update: ApplicationKitUpdate) -> dict[str, bool]:
    if update.status not in {"待确认", "已准备", "已投递", "已跳过"}:
        raise HTTPException(400, "未知投递包状态")
    with closing(connection()) as conn:
        result = conn.execute("UPDATE application_kits SET status = ?, updated_at = ? WHERE id = ?", (update.status, datetime.now(timezone.utc).isoformat(), kit_id))
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "投递包不存在")
    return {"ok": True}


@app.get("/api/alerts")
def list_alerts(status: str = "待发送") -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        return [dict(row) for row in conn.execute("""
          SELECT a.id, a.status AS alert_status, a.created_at AS alerted_at,
                 j.id AS job_id, j.title, j.company, j.city, j.url, j.score, j.score_reasons
          FROM alerts a JOIN jobs j ON j.id = a.job_id
          WHERE (? = '' OR a.status = ?)
          ORDER BY j.score DESC, a.created_at DESC
        """, (status, status))]


@app.patch("/api/alerts/{alert_id}")
def update_alert(alert_id: int, update: AlertUpdate) -> dict[str, bool]:
    if update.status not in {"待发送", "已发送", "已查看", "已忽略"}:
        raise HTTPException(400, "未知提醒状态")
    with closing(connection()) as conn:
        result = conn.execute("UPDATE alerts SET status = ?, handled_at = ? WHERE id = ?", (update.status, datetime.now(timezone.utc).isoformat(), alert_id))
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "提醒不存在")
    return {"ok": True}


@app.post("/api/alerts/dispatch")
def dispatch_alerts() -> dict[str, Any]:
    return dispatch_wecom_alerts()


@app.get("/api/companies")
def companies() -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        return [dict(r) for r in conn.execute("""
          SELECT c.*, COUNT(j.id) AS job_count
          FROM companies c LEFT JOIN jobs j ON j.company = c.name
          GROUP BY c.name ORDER BY CASE c.status WHEN 'active' THEN 0 ELSE 1 END, c.name
        """)]


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with closing(connection()) as conn:
        summary = conn.execute("""SELECT COUNT(*) total, SUM(score >= 75) strong,
          SUM(status = '已投递') applied, SUM(status = '面试中') interviewing FROM jobs""").fetchone()
        companies_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        active_sources = conn.execute("SELECT COUNT(*) FROM companies WHERE status = 'active'").fetchone()[0]
        pending_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = '待发送'").fetchone()[0]
    return {"total": summary["total"], "strong": summary["strong"] or 0, "applied": summary["applied"] or 0,
            "interviewing": summary["interviewing"] or 0, "companies": companies_count,
            "active_sources": active_sources, "pending_alerts": pending_alerts}


@app.get("/api/jobs/export")
def export_jobs() -> Response:
    jobs = list_jobs()
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(["评分", "职位", "公司", "城市", "来源", "状态", "链接", "评分原因"])
    for j in jobs:
        writer.writerow([j["score"], j["title"], j["company"], j["city"], j["source"], j["status"], j["url"], "；".join(j["score_reasons"])])
    return Response("\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=internship-radar.csv"})
