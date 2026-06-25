# 招标信息智能采集系统

从央企招标平台自动采集招标公告，存入本地数据库，通过 Web 页面浏览。

## 已支持站点

| 站点 | 名称 | 状态 | 备注 |
|------|------|------|------|
| chnenergybidding.com.cn | 国能e招 | 已完成 | 招标/中标/变更，详情页HTML提取 |
| cdt-ec.com | 大唐集团电商 | 已完成 | 招标/非招标，PDF附件提取 |
| ecp.sgcc.com.cn | 国家电网ECP | 已完成 | 招标/采购/中标/候选人公示，自动下载ZIP→提取DOCX正文 |
| sgccetp.com.cn | 国网电工交易 | 已完成 | 复用ECP适配器，招标/采购/中标/候选人公示 |
| neep.shop | 国能e购 | 已完成 | 询价/竞争性谈判/采购结果，JSONP分页+OSS详情页 |
| ecp.cgnpc.com.cn | 中广核电商 | 已完成 | 招标/资格预审/候选人/中标/采购，静态JSON分页+Playwright详情页 |
| www.lxjypt.cn | 陇西县公共资源交易 | 待校验 | JeeSite CMS，工程建设等；结构完成，条目解析/分页待联网校验 |
| gylpt.nxgyzb.com | 宁夏国资运营采购 | 已完成 | 静态CMS，招标/非招标/竞拍，Playwright列表+详情页提取 |
| ec.ceec.net.cn | 中国能建电子采购平台 | 已完成 | AjaxPro API，招标/采购/资格预审/候选人/中标，双格式解析 |
| www.chdtp.com.cn | 华电集团电子商务平台 | 已完成 | JSP表单POST+静态详情页，招标/询比/谈判/中标/候选人/终止 |
| ec.powerchina.cn | 中国电建设备物资集中采购平台 | 已完成 | SSR列表+PDF内嵌查看器，采购/变更/中标/终止，openFileById公开接口提取PDF正文 |
| ec.chng.com.cn | 华能集团电子商务平台 | 已完成 | Vue SPA+JSON API，瑞数反爬(stealth绕过)，招标/资格预审/候选人/中标/询比/谈判/竞价 |
| www.szecp.com.cn | 华润守正采购交易平台 | 已完成 | REST API列表+静态详情页，招标/更正/候选人/中标/终止/非招标/变更/结果，表格中标解析 |
| www.hebztb.com | 招标通电子招投标交易平台 | 已完成 | JSON API列表+SSR详情页，招标/变更/中标/废标，blurSearch元数据提取 |
| one.cnncecp.com | 中核集团电子采购平台 | 已完成 | 瑞数信息WAF(persistent context绕过)，招标/资格预审/中标/非招标，滑块验证码(OpenCV模板匹配)+PDF正文提取 |
| zjzcw.iccec.cn | 中交招采网 | 待校验 | Vue SPA+JSON API；接口已逆向，签名/字段待联网校验 |
| eps.xd.com.cn:8881 | 西电电子采购平台 | 待校验 | 登录墙，仅首页内联条目；采购/变更/中标/竞卖，解析待联网校验 |
| www.chinabidding.cn | 采购与招标网 | 待校验 | 阿里云WAF，须Playwright过挑战；招标公告入口已接入，其余分类/解析待联网校验 |
| ep.jxic.com | 江投集团电子采购平台 | 待校验 | Nuxt SSR，详情/notice/<id>；分类码/列表分页/解析待联网校验 |
| bulletin.cebpubservice.com | 中国招标投标公共服务平台 | 待校验 | 国家级聚合，搜索页/xxfbcmses/search/bulletin.html；categoryId/结果解析待联网校验 |
| dzzb.jnkgjtdzzbgs.com | 晋能控股招标采购 | 待校验 | 静态CMS（同宁夏平台），招标/采购；分类码/解析待联网校验 |
| eps.ctg.com.cn | 中国三峡集团电子采购平台 | 待校验 | CMS，招标/采购；分类码/解析待联网校验 |
| cgpt.china-an.cn | 中国安能电子采购平台 | 待校验 | WAF防护，须Playwright过挑战；列表/分类/解析全待联网校验 |
| www.hydlcg.com | 华源电力采购网 | 待校验 | Struts2+GBK，竞拍/谈判；端点/分页/解析待联网校验 |

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

# 采集国网电工交易（与ECP同平台，不同域名）
python -m bidding scrape --site sgcc_etp --max-pages 2

# 采集国能e购（询价/竞争性谈判/采购结果）
python -m bidding scrape --site neep --max-pages 2

# 采集中广核电商（招标/资格预审/候选人/中标/采购）
python -m bidding scrape --site cgnpc --max-pages 2

# 采集陇西县公共资源交易（JeeSite CMS；结构完成，解析待联网校验）
python -m bidding scrape --site lxjypt --max-pages 2

# 采集宁夏国资运营采购
python -m bidding scrape --site nxgyzb --max-pages 2

# 采集中国能建电子采购平台（AjaxPro API，招标/采购/资格预审/候选人/中标）
python -m bidding scrape --site ceec --max-pages 2

# 采集华电集团电子商务平台（招标/询比/谈判/中标/候选人/终止）
python -m bidding scrape --site chdtp --max-pages 2

# 采集中国电建设备物资集中采购平台（采购/变更/中标/终止，PDF正文提取）
python -m bidding scrape --site powerchina --max-pages 2

# 采集华能集团电子商务平台（招标/资格预审/候选人/中标/询比/谈判/竞价）
python -m bidding scrape --site chng --max-pages 2

# 采集华润守正采购交易平台（招标/更正/候选人/中标/终止/非招标/变更/结果）
python -m bidding scrape --site szecp --max-pages 2

# 采集中交招采网（Vue SPA+JSON API；接口已逆向，签名/字段待联网校验）
python -m bidding scrape --site iccec --max-pages 2

# 采集西电电子采购平台（登录墙，仅首页内联条目；解析待联网校验）
python -m bidding scrape --site xd_eps --max-pages 1

# 采集采购与招标网（阿里云WAF，须Playwright过挑战；解析待联网校验）
python -m bidding scrape --site chinabidding --max-pages 1

# 采集江投集团电子采购平台（Nuxt SSR；解析待联网校验）
python -m bidding scrape --site jxic --max-pages 1

# 采集中国招标投标公共服务平台（国家级聚合；解析待联网校验）
python -m bidding scrape --site cebpubservice --max-pages 1

# 采集晋能控股招标采购（静态CMS；解析待联网校验）
python -m bidding scrape --site jnkg --max-pages 1

# 采集中国三峡集团电子采购平台（CMS；解析待联网校验）
python -m bidding scrape --site ctg --max-pages 1

# 采集中国安能电子采购平台（WAF防护；解析待联网校验）
python -m bidding scrape --site china_an --max-pages 1

# 采集华源电力采购网（Struts2+GBK；解析待联网校验）
python -m bidding scrape --site hydl --max-pages 1

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
│   ├── sgcc_ecp.py        # 国家电网ECP适配器
│   ├── sgcc_etp.py        # 国网电工交易适配器（继承ECP）
│   ├── neep.py            # 国能e购适配器
│   ├── cgnpc.py           # 中广核电商适配器

│   ├── lxjypt.py          # 陇西县公共资源交易适配器
│   ├── nxgyzb.py          # 宁夏国资运营采购适配器
│   ├── xd_eps.py          # 西电电子采购平台适配器（登录墙，仅首页内联）
│   ├── iccec.py           # 中交招采网适配器（Vue SPA + JSON API）
│   └── cebpubservice.py   # 中国招标投标公共服务平台适配器（国家级聚合）
│   ├── jxic.py            # 江投集团电子采购平台适配器（Nuxt SSR）
│   ├── chinabidding.py    # 采购与招标网适配器（阿里云WAF，须Playwright）

│   ├── ceec.py            # 中国能建电子采购平台适配器（AjaxPro API）
│   ├── chdtp.py           # 华电集团电子商务平台适配器（JSP表单POST）
│   ├── powerchina.py      # 中国电建设备物资集中采购平台适配器（PDF提取）
│   ├── chng.py            # 华能集团电子商务平台适配器（Vue SPA + JSON API）
│   ├── szecp.py           # 华润守正采购交易平台适配器（REST API + 静态详情页）
│   ├── hebztb.py          # 招标通电子招投标交易平台适配器（JSON API + SSR详情页）
│   ├── cnnc.py            # 中核集团电子采购平台适配器（瑞数WAF + PDF提取）
│   ├── jnkg.py            # 晋能控股招标采购适配器（静态CMS）
│   ├── ctg.py             # 中国三峡集团电子采购平台适配器（CMS）
│   ├── china_an.py        # 中国安能电子采购平台适配器（WAF防护）
│   ├── hydl.py            # 华源电力采购网适配器（Struts2+GBK）
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
