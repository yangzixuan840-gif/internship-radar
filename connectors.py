"""Low-frequency clients for public, unauthenticated recruiting APIs.

Each connector intentionally uses a small page cap and has no browser
automation, login, CAPTCHA handling, or application workflow.  Upstream APIs
change frequently, so a connector failure is reported to the UI rather than
silently treated as an empty result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = "InternshipRadar/0.2 (+https://github.com/yangzixuan840-gif/internship-radar)"


@dataclass
class SyncResult:
    company: str
    jobs: list[dict[str, Any]]
    message: str


def request_json(url: str, *, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = {"Accept": "application/json, text/plain, */*", "User-Agent": USER_AGENT, **(headers or {})}
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=payload, headers=request_headers, method="POST" if payload else "GET"), timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"upstream HTTP {error.code}") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"upstream unavailable: {error}") from error


def text(*parts: Any) -> str:
    """Join meaningful non-empty fields without leaking Python representations."""
    return "\n".join(str(part).strip() for part in parts if part and str(part).strip())


def bytedance_internships() -> SyncResult:
    """Fetch one capped page of ByteDance's public campus internship feed."""
    payload = {
        "keyword": "",
        "limit": 100,
        "offset": 0,
        "portal_type": 3,
        "portal_entrance": 1,
        "language": "zh",
        "recruitment_id_list": ["202"],  # official campus API: internship channel
    }
    data = request_json(
        "https://jobs.bytedance.com/api/v1/search/job/posts",
        body=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Origin": "https://jobs.bytedance.com",
            "Referer": "https://jobs.bytedance.com/campus/position?type=3",
            "portal-channel": "campus",
            "portal-platform": "pc",
            "website-path": "campus",
        },
    )
    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or "ByteDance API returned an error")
    posts = data.get("data", {}).get("job_post_list", [])
    jobs = []
    for post in posts:
        post_id = str(post.get("id") or "")
        cities = post.get("city_list") or []
        city = " / ".join(c.get("name", "") for c in cities if c.get("name")) or (post.get("city_info") or {}).get("name", "")
        jobs.append({
            "title": post.get("title") or "未命名职位",
            "company": "字节跳动",
            "city": city,
            "description": text((post.get("job_category") or {}).get("name"), post.get("description"), post.get("requirement")),
            "url": f"https://jobs.bytedance.com/campus/position/{post_id}/detail" if post_id else "https://jobs.bytedance.com/campus/position?type=3",
            "source": "字节跳动官网 API",
        })
    return SyncResult("字节跳动", jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 100）")


def tencent_internships() -> SyncResult:
    """Resolve Tencent's live internship project mappings, then fetch one page."""
    headers = {"Origin": "https://join.qq.com", "Referer": "https://join.qq.com/post.html"}
    mapping = request_json("https://join.qq.com/api/v1/position/getProjectMapping", headers=headers)
    if mapping.get("status") != 0:
        raise RuntimeError(mapping.get("message") or "Tencent project mapping unavailable")
    internship_ids = []
    for group in mapping.get("data") or []:
        for project in group.get("subProjectList") or []:
            if group.get("recruitType") == 2 or "实习" in (project.get("projectName") or ""):
                if project.get("mappingId") is not None:
                    internship_ids.append(int(project["mappingId"]))
    if not internship_ids:
        raise RuntimeError("Tencent internship channel is not currently listed")
    data = request_json(
        "https://join.qq.com/api/v1/position/searchPosition",
        body={
            "projectIdList": [],
            "projectMappingIdList": internship_ids,
            "keyword": "",
            "bgList": [],
            "workCountryType": 1,
            "workCityList": [],
            "recruitCityList": [],
            "positionFidList": [],
            "pageIndex": 1,
            "pageSize": 100,
        },
        headers=headers,
    )
    if data.get("status") != 0:
        raise RuntimeError(data.get("message") or "Tencent API returned an error")
    posts = data.get("data", {}).get("positionList", [])
    jobs = [{
        "title": post.get("positionTitle") or "未命名职位",
        "company": "腾讯",
        "city": post.get("workCities") or "",
        "description": text(post.get("projectName"), post.get("recruitLabelName"), post.get("bgs")),
        "url": f"https://join.qq.com/post_detail.html?postid={post['postId']}" if post.get("postId") else "https://join.qq.com/post.html",
        "source": "腾讯官网 API",
    } for post in posts]
    return SyncResult("腾讯", jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 100）")


def meituan_internships() -> SyncResult:
    """Fetch one capped page of Meituan's public internship feed."""
    data = request_json(
        "https://zhaopin.meituan.com/api/official/job/getJobList",
        body={
            "page": {"pageNo": 1, "pageSize": 100},
            "jobShareType": "1",
            "keywords": "",
            "cityList": [],
            "department": [],
            "jobType": [{"code": "2", "subCode": []}],
        },
        headers={"Origin": "https://zhaopin.meituan.com", "Referer": "https://zhaopin.meituan.com/web/campus"},
    )
    if data.get("status") != 1:
        raise RuntimeError(data.get("message") or "Meituan API returned an error")
    posts = data.get("data", {}).get("list", [])
    jobs = []
    for post in posts:
        job_id = str(post.get("jobUnionId") or "")
        city = " / ".join(item.get("name", "") for item in (post.get("cityList") or []) if item.get("name"))
        department = (post.get("department") or [{}])[0].get("name", "")
        jobs.append({
            "title": post.get("name") or "未命名职位",
            "company": "美团",
            "city": city,
            "description": text(department, post.get("jobFamily"), post.get("jobFamilyGroup"), post.get("jobDuty"), post.get("jobRequirement")),
            "url": f"https://zhaopin.meituan.com/web/position/detail?jobUnionId={job_id}&jobShareType=1&highlightType=campus" if job_id else "https://zhaopin.meituan.com/web/campus",
            "source": "美团官网 API",
        })
    return SyncResult("美团", jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 100）")


CONNECTORS = {"字节跳动": bytedance_internships, "腾讯": tencent_internships, "美团": meituan_internships}
