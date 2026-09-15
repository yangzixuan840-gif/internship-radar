# 国内实习雷达 · Internship Radar

一个面向中国大陆技术实习的个人职位情报工具。它把官网职位和平台职位统一到一个本地职位库，按可解释规则为每条职位评分，并记录投递进度。

> 这是一个作品集项目：强调可维护的职位数据管道与个人匹配，不做自动投递、不绕过验证码，也不包含任何个人数据。

## 为什么做它

国内实习职位往往分散在招聘官网、校园招聘页和平台上；职位描述也不总能直接判断是否符合毕业时间、到岗时长、地点和技术方向。实习雷达将这些判断固定为透明的规则，帮助求职者把精力放在高匹配机会和高质量投递上。

## 当前功能

- 手工录入职位，或通过 `POST /api/jobs/import` 批量导入 JSON；
- URL 级去重，重复导入时更新职位内容和评分；
- 0–100 的可解释评分：岗位方向、技能、地点、时长、到岗频率和实习身份；
- 搜索、城市分组筛选、收藏、投递/面试状态和 CSV 导出；
- 18 个国内公司官网入口；为逐家公司实现低频、公开接口优先的 connector 预留数据模型；
- 已接入字节跳动、腾讯、美团、小红书、京东、滴滴的公开职位 API；点击“同步已接入官网”即可手动增量同步；
- SQLite 本地存储；Docker 一键启动；个人资料配置不提交到 Git。

## 架构

```text
官网 / 平台导入
       │
       ▼
FastAPI API ──► SQLite 职位库 ──► 规则评分 ──► Web 控制台 / CSV
       │
       └──► 公司来源与 connector 状态
```

## 快速开始

要求：Python 3.10+。

```powershell
git clone https://github.com/<your-account>/internship-radar.git
cd internship-radar
Copy-Item config/profile.example.json config/profile.json
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

也可以使用 Docker：

```powershell
docker compose up --build
```

数据写入 `data/radar.db`，本地个人资料写入 `config/profile.json`；两者都已被 `.gitignore` 排除。

## 个人配置

把 `config/profile.example.json` 复制为 `config/profile.json` 后，填写你的毕业时间、到岗窗口、城市优先级、目标方向与技能。该文件只保留在本地，应用启动时自动加载。

## 职位导入格式

向 `POST /api/jobs/import` 发送 JSON 数组；每个对象至少应包括：

```json
{
  "title": "后端开发实习生",
  "company": "示例公司",
  "city": "上海",
  "description": "Java、Spring Boot、MySQL、Redis；每周 5 天，连续 2 个月。",
  "url": "https://example.com/job/1",
  "source": "官网",
  "duration_weeks": 8,
  "work_days": 5
}
```

## 采集原则与路线图

当前可同步的来源是字节跳动、腾讯、美团、小红书、京东和滴滴。每个 connector 都只访问对应官网提供的未登录职位接口，大部分单次最多读取 100 条（滴滴为 6 页上限），并对每家公司设置 20 分钟的本地同步冷却时间。优先顺序是：公开职位 API → 官网公开页面 → 人工导入。不会尝试绕过登录、验证码、反爬或网站访问限制。

下一步：

1. 为少量目标公司增加经过验证的公开职位 API connector；
2. 增加定时增量导入、职位变更检测与提醒；
3. 增加针对简历技能的权重编辑与评分解释视图；
4. 增加测试、CI 与部署示例。

## 技术栈

Python · FastAPI · Pydantic · SQLite · Vanilla JavaScript · Docker

## License

MIT
