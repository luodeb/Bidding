# 招标信息智能采集系统

从央企招标平台自动采集招标公告，存入本地数据库，通过 Web 页面浏览。

## 已支持站点

| 站点 | 名称 | 状态 | 备注 |
|------|------|------|------|
| chnenergybidding.com.cn | 国能e招 | 已完成 | 招标/中标/变更，详情页HTML提取 |
| cdt-ec.com | 大唐集团电商 | 已完成 | 招标/非招标，PDF附件提取 |
| ecp.sgcc.com.cn | 国家电网ECP | 已完成 | 招标/采购/中标/候选人公示，自动下载ZIP→提取DOCX正文 |
| sgccetp.com.cn | 国网电工交易 | 待开发 | |
| neep.shop | 国能e购 | 待开发 | |

新增站点只需在 `src/bidding/adapters/` 下创建适配器文件。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

## 使用

### 查看已注册站点

```bash
python -m bidding list-sites
```

### 采集招标列表

```bash
# 采集国能e招，最多翻5页
python -m bidding scrape --site chnenergy --max-pages 5

# 采集大唐集团
python -m bidding scrape --site cdt_ec --max-pages 2

# 采集国家电网ECP（支持招标、采购、中标、候选人公示）
python -m bidding scrape --site sgcc_ecp --max-pages 2

# 有头模式（可以看到浏览器操作，方便调试）
python -m bidding scrape --site chnenergy --max-pages 3 --headed

# 采集所有站点
python -m bidding scrape
```

参数说明：
- `--site, -s` 指定站点，可多次使用，不指定则采集全部
- `--max-pages, -p` 每种公告类型最大翻页数，默认 50
- `--headless/--headed` 无头模式（默认）或有头模式
- `--stop-after` 连续遇到 N 条重复记录后停止（增量采集），默认 10

### 补采公告正文

列表采集只抓取标题和基本信息，正文需要单独采集：

```bash
# 采集前50条缺少正文的记录（通过详情页）
python -m bidding fetch-details --site chnenergy --limit 50

# 采集全部缺少正文的记录
python -m bidding fetch-details --limit 999
```

### 从PDF提取正文

大唐等站点公告正文以PDF形式提供，采集时自动提取。也可对已有记录补提取：

```bash
# 从PDF附件提取正文（大唐集团等）
python -m bidding fetch-pdf --site cdt_ec --limit 50
```

### 启动 Web 页面

```bash
python -m bidding web
```

打开 http://localhost:8000 浏览，支持按公告类型筛选和关键词搜索。

### 查看统计

```bash
python -m bidding stats
```

## 项目结构

```
src/bidding/
├── cli.py                 # 命令行入口
├── core/
│   ├── engine.py          # 采集引擎
│   ├── detail_fetcher.py  # 详情页采集
│   ├── pdf_fetcher.py     # PDF正文提取
│   ├── dedup.py           # 去重
│   └── pipeline.py        # 数据管道
├── models/
│   ├── schema.py          # BidNotice 数据模型
│   ├── db.py              # 数据库表定义
│   └── enums.py           # 公告类型等枚举
├── adapters/
│   ├── base.py            # 适配器基类
│   ├── registry.py        # 自动发现与注册
│   ├── chnenergy.py       # 国能e招适配器
│   ├── cdt_ec.py          # 大唐集团适配器
│   └── sgcc_ecp.py        # 国家电网ECP适配器
├── storage/
│   ├── database.py        # 数据库连接
│   └── repository.py      # 数据读写
├── utils/
│   ├── pdf.py             # PDF文本提取工具
│   └── doc.py             # DOCX/DOC文本提取工具（国家电网ZIP→DOCX链）
└── web/
    ├── app.py             # FastAPI 应用
    └── templates/         # 页面模板
```

## 数据存储

SQLite 数据库文件位于 `data/bidding.db`，主要字段：

| 字段 | 说明 |
|------|------|
| title | 公告标题 |
| notice_type | 类型（招标/中标/变更等） |
| notice_id | 公告编号 |
| publish_date | 发布日期 |
| source_url | 原文链接 |
| content | 公告正文 |
| purchaser | 招标人 |
| budget | 预算金额 |
| winner | 中标人 |
| win_amount | 中标金额 |
