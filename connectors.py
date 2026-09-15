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
from urllib.parse import urlencode
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


def request_form(url: str, fields: dict[str, str], *, headers: dict[str, str]) -> dict[str, Any]:
    """POST a standard URL-encoded public search form."""
    request_headers = {"Accept": "application/json, text/plain, */*", "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded", **headers}
    try:
        with urlopen(Request(url, data=urlencode(fields).encode("utf-8"), headers=request_headers, method="POST"), timeout=15) as response:
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


def xiaohongshu_internships() -> SyncResult:
    """Fetch a capped campus page; Xiaohongshu includes intern tracks in it."""
    data = request_json(
        "https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition",
        body={"recruitType": "campus", "pageNum": 1, "pageSize": 100},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Origin": "https://job.xiaohongshu.com",
            "Referer": "https://job.xiaohongshu.com/campus/position",
        },
    )
    if not (data.get("success") is True or data.get("statusCode") == 200):
        raise RuntimeError(data.get("alertMsg") or data.get("errorMsg") or "Xiaohongshu API returned an error")
    posts = data.get("data", {}).get("list", [])
    jobs = [{
        "title": post.get("positionName") or "未命名职位",
        "company": "小红书",
        "city": post.get("workplace") or "",
        "description": text(post.get("jobType"), post.get("jobProjectName"), post.get("duty")),
        "url": f"https://job.xiaohongshu.com/campus/position/{post['positionId']}" if post.get("positionId") else "https://job.xiaohongshu.com/campus/position",
        "source": "小红书官网 API",
    } for post in posts]
    return SyncResult("小红书", jobs, f"已读取 {len(jobs)} 条校园招聘职位（含实习项目，单次上限 100）")


def jd_internships() -> SyncResult:
    """Fetch JD's public internship bucket only, capped to one page."""
    data = request_json(
        "https://campus.jd.com/api/wx/position/page?type=internship",
        body={
            "pageSize": 100,
            "pageIndex": 0,
            "parameter": {"positionName": "", "planIdList": [], "positionDeptList": [], "jobDirectionCodeList": [], "workCityCodeList": []},
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://campus.jd.com/",
        },
    )
    if data.get("success") is not True:
        raise RuntimeError(data.get("errorMessage") or "JD API returned an error")
    posts = data.get("body", {}).get("items", [])
    jobs = []
    for post in posts:
        requirement = post.get("requirementVoList") or []
        cities = " / ".join(item.get("workCity", "") for item in requirement if item.get("workCity"))
        jobs.append({
            "title": post.get("positionName") or "未命名职位",
            "company": "京东",
            "city": cities,
            "description": text(post.get("jobDirection"), post.get("workContent"), post.get("qualification")),
            "url": f"https://campus.jd.com/#/newDetails?publishId={post['publishId']}" if post.get("publishId") else "https://campus.jd.com/",
            "source": "京东官网 API",
        })
    return SyncResult("京东", jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 100）")


def didi_internships() -> SyncResult:
    """Read at most six public pages and keep the campus/intern JR entries."""
    jobs, seen = [], set()
    for page in range(1, 7):
        query = urlencode({"page": page, "size": 16})
        data = request_json(
            f"https://talent.didiglobal.com/recruit-portal-service/api/job/front/list?{query}",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://talent.didiglobal.com/",
            },
        )
        if (data.get("meta") or {}).get("code") != 0:
            raise RuntimeError((data.get("meta") or {}).get("message") or "Didi API returned an error")
        for post in (data.get("data") or {}).get("items") or []:
            jd_no = post.get("jdNo") or ""
            if not jd_no.startswith("JR") or post.get("jdId") in seen:
                continue
            seen.add(post.get("jdId"))
            title = post.get("jobName") or "未命名职位"
            if title.endswith(f" ({jd_no})"):
                title = title[: -len(jd_no) - 3]
            jobs.append({
                "title": title,
                "company": "滴滴",
                "city": post.get("workArea") or "",
                "description": text(post.get("deptName"), post.get("jobType")),
                "url": f"https://talent.didiglobal.com/campus#/position/{post['jdId']}/detail" if post.get("jdId") else "https://talent.didiglobal.com/",
                "source": "滴滴官网 API",
            })
    return SyncResult("滴滴", jobs, f"已读取 {len(jobs)} 条公开校园/实习职位（6 页上限）")


def baidu_internships() -> SyncResult:
    """Fetch a capped page of Baidu's daily-internship public board."""
    data = request_form(
        "https://talent.baidu.com/httservice/getPostListNew",
        {"recruitType": "INTERN", "keyWord": "", "curPage": "1", "pageSize": "20", "projectType": "-1"},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://talent.baidu.com/jobs/list?recruitType=INTERN",
        },
    )
    if data.get("status") != "ok":
        raise RuntimeError(data.get("message") or "Baidu API returned an error")
    posts = data.get("data", {}).get("list", [])
    jobs = [{
        "title": post.get("name") or "未命名职位",
        "company": "百度",
        "city": post.get("workPlace") or "",
        "description": text(post.get("postType"), post.get("projectType"), post.get("workContent"), post.get("serviceCondition")),
        "url": f"https://talent.baidu.com/jobs/detail/INTERN/{post['postId']}" if post.get("postId") else "https://talent.baidu.com/jobs/list?recruitType=INTERN",
        "source": "百度官网 API",
    } for post in posts]
    return SyncResult("百度", jobs, f"已读取 {len(jobs)} 条公开日常实习职位（单次上限 20）")


def bilibili_internships() -> SyncResult:
    """Use Bilibili's anonymous CSRF handshake, then request intern listings."""
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-AppKey": "ops.ehr-api.auth",
        "X-UserType": "2",
        "Referer": "https://jobs.bilibili.com/",
    }
    csrf = request_json("https://jobs.bilibili.com/api/auth/v1/csrf/token", headers=base_headers)
    token = csrf.get("data")
    if csrf.get("code") != 0 or not token:
        raise RuntimeError(csrf.get("message") or "Bilibili CSRF handshake failed")
    data = request_json(
        "https://jobs.bilibili.com/api/campus/position/positionList",
        body={"pageNum": 1, "pageSize": 100, "positionName": "", "deptCodeList": [], "workTypeList": [0], "positionTypeList": [], "workLocationList": []},
        headers={**base_headers, "X-CSRF": token, "Cookie": f"X-CSRF={token}"},
    )
    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or "Bilibili API returned an error")
    posts = data.get("data", {}).get("list", [])
    jobs = [{
        "title": post.get("positionName") or "未命名职位",
        "company": "哔哩哔哩",
        "city": post.get("workLocation") or "",
        "description": text(post.get("postCodeName"), post.get("positionDescription")),
        "url": f"https://jobs.bilibili.com/campus/positions/{post['id']}" if post.get("id") else "https://jobs.bilibili.com/campus/positions",
        "source": "哔哩哔哩官网 API",
    } for post in posts]
    return SyncResult("哔哩哔哩", jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 100）")


def netease_internships() -> SyncResult:
    """Fetch one large page from NetEase's public campus/internship board."""
    data = request_json(
        "https://hr.163.com/api/hr163/position/queryPage",
        body={"currentPage": 1, "pageSize": 100, "workType": "1", "keyword": ""},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://hr.163.com/job-list.html?workType=1",
        },
    )
    if data.get("code") != 200:
        raise RuntimeError(data.get("msg") or "NetEase API returned an error")
    posts = data.get("data", {}).get("list", [])
    jobs = [{
        "title": post.get("name") or "未命名职位",
        "company": "网易",
        "city": " / ".join(post.get("workPlaceNameList") or []),
        "description": text(post.get("firstPostTypeName"), post.get("firstDepName"), post.get("description"), post.get("requirement")),
        "url": f"https://hr.163.com/job-detail.html?id={post['id']}" if post.get("id") else "https://hr.163.com/job-list.html?workType=1",
        "source": "网易官网 API",
    } for post in posts]
    return SyncResult("网易", jobs, f"已读取 {len(jobs)} 条公开校园/实习职位（单次上限 100）")


def feishu_internships(company: str, host: str, channel: str) -> SyncResult:
    """Shared client for official Feishu Hire campus portals."""
    data = request_json(
        f"https://{host}/api/v1/search/job/posts",
        body={"keyword": "", "limit": 100, "offset": 0, "portal_type": 3, "portal_entrance": 1, "language": "zh", "recruitment_id_list": ["202"]},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Origin": f"https://{host}", "Referer": f"https://{host}/{channel}",
            "portal-channel": channel, "portal-platform": "pc", "website-path": channel,
        },
    )
    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or f"{company} API returned an error")
    posts = data.get("data", {}).get("job_post_list", [])
    jobs = []
    for post in posts:
        post_id = str(post.get("id") or "")
        city = " / ".join(item.get("name", "") for item in (post.get("city_list") or []) if item.get("name"))
        jobs.append({
            "title": post.get("title") or "未命名职位", "company": company, "city": city,
            "description": text((post.get("job_category") or {}).get("name"), (post.get("job_function") or {}).get("name"), post.get("description"), post.get("requirement")),
            "url": f"https://{host}/{channel}/position/{post_id}/detail" if post_id else f"https://{host}/{channel}",
            "source": f"{company}官网 API",
        })
    return SyncResult(company, jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 100）")


def xpeng_internships() -> SyncResult:
    return feishu_internships("小鹏汽车", "xiaopeng.jobs.feishu.cn", "campus")


def nio_internships() -> SyncResult:
    return feishu_internships("蔚来", "nio.jobs.feishu.cn", "campus")


def trip_internships() -> SyncResult:
    """Ctrip's public feed is complete in one response; filter internships locally."""
    data = request_json(
        "https://careers.ctrip.com/api/hrrecruit/getJobAd",
        body={"condition": {"pageIndex": 1, "pageSize": 100}},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Origin": "https://careers.ctrip.com", "Referer": "https://careers.ctrip.com/campus",
        },
    )
    if data.get("retCode") != "201":
        raise RuntimeError(data.get("retMessage") or "Trip API returned an error")
    posts = [item for item in (data.get("retValue", {}).get("recruitJobAdList", []) or []) if item.get("kind") == "3" or "实习" in (item.get("jobTitle") or "")]
    jobs = [{
        "title": post.get("jobTitle") or "未命名职位", "company": "携程", "city": post.get("cityName") or "",
        "description": text(post.get("jobFamilyGroupName"), post.get("buName"), post.get("duty"), post.get("requirements")),
        "url": f"https://careers.ctrip.com/campus#/experienced/job-detail/{post['fromId']}" if post.get("fromId") else "https://careers.ctrip.com/campus",
        "source": "携程官网 API",
    } for post in posts]
    return SyncResult("携程", jobs, f"已读取 {len(jobs)} 条公开实习职位")


def iflytek_internships() -> SyncResult:
    """Fetch the iFlytek Beisen portal's dedicated intern category."""
    data = request_json(
        "https://iflytek.zhiye.com/api/Jobad/GetJobAdPageList",
        body={"PageIndex": 0, "PageSize": 50, "KeyWords": "", "SpecialType": 0, "PortalId": "", "Category": ["3"], "DisplayFields": ["Category", "Kind", "LocId", "Org", "PostDate"]},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Origin": "https://iflytek.zhiye.com", "Referer": "https://iflytek.zhiye.com/jobs",
            "x-requested-with": "xmlhttprequest", "langtype": "zh_CN",
        },
    )
    if data.get("Code") != 200:
        raise RuntimeError(data.get("Message") or "iFlytek API returned an error")
    posts = data.get("Data") or []
    jobs = [{
        "title": post.get("JobAdName") or "未命名职位", "company": "科大讯飞", "city": " / ".join(post.get("LocNames") or []),
        "description": text(post.get("Category"), post.get("Org"), post.get("Duty"), post.get("Require")),
        "url": f"https://iflytek.zhiye.com/intern/detail?jobAdId={post.get('JobAdId') or post.get('Id')}" if (post.get("JobAdId") or post.get("Id")) else "https://iflytek.zhiye.com/jobs",
        "source": "科大讯飞官网 API",
    } for post in posts]
    return SyncResult("科大讯飞", jobs, f"已读取 {len(jobs)} 条公开实习职位（单次上限 50）")


def horizon_internships() -> SyncResult:
    """Fetch Horizon Robotics' public Wecruit campus channel."""
    channel = "SU6409ef49bef57c635fd390a6"
    data = request_form(
        f"https://wecruit.hotjob.cn/wecruit/positionInfo/listPosition/{channel}?iSaJAx=isAjax&request_locale=zh_CN",
        {"isFrompb": "true", "recruitType": "1", "pageSize": "100", "currentPage": "1"},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Origin": "https://wecruit.hotjob.cn", "Referer": f"https://wecruit.hotjob.cn/{channel}/pb/school.html", "X-Requested-With": "XMLHttpRequest",
        },
    )
    if data.get("state") != "200":
        raise RuntimeError(data.get("msg") or "Horizon API returned an error")
    posts = (data.get("data") or {}).get("pageForm", {}).get("pageData", [])
    jobs = [{
        "title": post.get("postName") or "未命名职位", "company": "地平线", "city": post.get("workPlaceStr") or "",
        "description": text(post.get("postTypeName"), post.get("department"), post.get("description"), post.get("requirement")),
        "url": f"https://wecruit.hotjob.cn/{channel}/pb/school.html#/postDetail?postId={post['postId']}" if post.get("postId") else f"https://wecruit.hotjob.cn/{channel}/pb/school.html",
        "source": "地平线官网 API",
    } for post in posts]
    return SyncResult("地平线", jobs, f"已读取 {len(jobs)} 条公开校园/实习职位（单次上限 100）")


CONNECTORS = {
    "字节跳动": bytedance_internships,
    "腾讯": tencent_internships,
    "美团": meituan_internships,
    "小红书": xiaohongshu_internships,
    "京东": jd_internships,
    "滴滴": didi_internships,
    "百度": baidu_internships,
    "哔哩哔哩": bilibili_internships,
    "网易": netease_internships,
    "小鹏汽车": xpeng_internships,
    "蔚来": nio_internships,
    "携程": trip_internships,
    "科大讯飞": iflytek_internships,
    "地平线": horizon_internships,
}
