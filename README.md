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
- 统一公司筛选：75 家官网来源均可作为筛选维度；公司卡片展示“已接入同步 / 待适配”和已入库岗位数；
- 75 个国内中大型公司官网入口；为逐家公司实现低频、公开接口优先的 connector 预留数据模型；
- 已接入字节跳动、腾讯、美团、小红书、京东、滴滴、百度、哔哩哔哩、网易、携程、科大讯飞、地平线、小鹏汽车、蔚来、小米、OPPO、vivo、MiniMax、千寻智能、星猿哲科技的公开职位 API；点击“同步已接入官网”即可手动增量同步；
- 新增岗位提醒出站队列：自动同步的新高匹配岗位会只入队一次，等待选择通知渠道后发送；同步轮次与失败原因可审计；
- 企业微信机器人通知：配置本地 Webhook 后，Worker 会将待提醒高匹配岗位合并成摘要推送，并只标记成功发送的岗位；
- 简历版本与投递包：简历文件仅保存在本机；可从任意岗位生成技能命中、待核对缺口、投递前检查项与不虚构经历的投递说明草稿；
- 受控浏览器填表：只对用户确认“已准备”的投递包打开官网、填写无歧义基础字段和上传本地简历；不处理验证码、不填写主观题、更不会点击最终提交；
- SQLite 本地存储；Docker 一键启动；个人资料配置不提交到 Git。

## 架构

```text
官网 / 平台导入
       │
       ▼
同步 Worker ──► FastAPI API ──► SQLite 职位库 ──► 规则评分 ──► 提醒出站队列
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

### 企业微信机器人提醒

在企业微信群添加机器人，复制其 Webhook 地址到本地 `.env`：

```text
WECOM_BOT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的密钥
```

可先复制 `.env.example` 为 `.env`。Webhook 不会输出到日志、不会写入数据库，也不应提交到 Git。启动 `docker compose up --build` 后，Worker 会在每轮同步后推送达到 `alert_threshold` 的新岗位；未配置 Webhook 时只保留本地待发送队列。

### 受控投递填表

先在网页中生成并确认投递包，再将配置模板复制为本地文件：

```powershell
Copy-Item config/application.example.json config/application.json
pip install -r requirements-apply.txt
playwright install chromium
python apply_worker.py --kit <投递包编号>
```

脚本会打开可见浏览器，最多填写姓名、邮箱、电话、城市和文件上传控件，并截图记录本次操作。它不会点击任何“投递 / 提交 / 下一步”按钮；验证码、登录、主观问题和最终提交均需用户亲自处理。

## 个人配置

把 `config/profile.example.json` 复制为 `config/profile.json` 后，填写你的毕业时间、到岗窗口、城市优先级、目标方向与技能。`alert_threshold` 是进入提醒队列的最低分数，`sync_minutes` 是后台同步间隔（最低 20 分钟）。该文件只保留在本地，应用启动时自动加载。

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

当前可同步的来源是字节跳动、腾讯、美团、小红书、京东、滴滴、百度、哔哩哔哩、网易、携程、科大讯飞、地平线、小鹏汽车、蔚来、小米、OPPO、vivo、MiniMax、千寻智能和星猿哲科技。每个 connector 都只访问对应官网提供的未登录职位接口，大部分单次最多读取 100 条（滴滴为 6 页上限、百度为 20 条上限），并对每家公司设置 20 分钟的本地同步冷却时间。75 家公司都可在页面的“公司”下拉框中筛选；手工录入或后续同步得到的岗位会进入同一套方向、技能、城市、时长和到岗频率评分。待适配来源只会显示官网入口，完成接口验证后才会启用同步。优先顺序是：公开职位 API → 官网公开页面 → 人工导入。不会尝试绕过登录、验证码、反爬或网站访问限制。

下一步：

1. 为少量目标公司增加经过验证的公开职位 API connector；
2. 接入邮件、Telegram 或 ntfy 等由用户配置的通知渠道；
3. 增加针对简历技能的权重编辑与评分解释视图；
4. 针对少数常用官网招聘系统增加字段映射；
5. 增加测试、CI 与部署示例。

## 技术栈

Python · FastAPI · Pydantic · SQLite · Vanilla JavaScript · Docker

## License

MIT
