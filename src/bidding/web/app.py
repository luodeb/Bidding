from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from bidding.models.db import BidNoticeRecord
from bidding.storage.database import get_session_factory, init_db

app = FastAPI(title="招标信息系统")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_PDF_DIR = _DATA_DIR / "pdf"

SITE_LABELS = {
    "chnenergy": "国能e招",
    "cdt_ec": "大唐集团",
    "sgcc_ecp": "国家电网ECP",
    "sgcc_etp": "国网电工交易",
    "neep": "国能e购",
    "cgnpc": "中广核电商",
    "lxjypt": "陇西县公共资源交易",
    "nxgyzb": "宁夏国资运营采购",
    "iccec": "中交招采网",
    "xd_eps": "西电电子采购平台",
    "chinabidding": "采购与招标网",
    "jxic": "江投集团电子采购平台",
    "cebpubservice": "中国招标投标公共服务平台",
    "ceec": "中国能建",
    "chdtp": "华电集团",
    "powerchina": "中国电建",
    "chng": "华能集团",
    "szecp": "华润守正",
    "hebztb": "招标通",
    "cnnc": "中核集团",
    "jnkg": "晋能控股招标采购",
    "ctg": "中国三峡集团电子采购平台",
    "china_an": "中国安能电子采购平台",
    "hydl": "华源电力采购网",
}

NOTICE_TYPE_LABELS = {
    "bid_announcement": "招标公告",
    "prequalification": "资格预审",
    "non_bid_announcement": "非招标公告",
    "change_announcement": "变更公告",
    "candidate_publicity": "候选人公示",
    "win_announcement": "中标公告",
    "termination": "终止公告",
}


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    page: int = Query(1, ge=1),
    notice_type: str = Query("", alias="type"),
    q: str = Query(""),
):
    page_size = 20
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(BidNoticeRecord).order_by(BidNoticeRecord.publish_date.desc(), BidNoticeRecord.id.desc())
        count_stmt = select(func.count(BidNoticeRecord.id))

        if notice_type:
            stmt = stmt.where(BidNoticeRecord.notice_type == notice_type)
            count_stmt = count_stmt.where(BidNoticeRecord.notice_type == notice_type)
        if q:
            stmt = stmt.where(BidNoticeRecord.title.contains(q))
            count_stmt = count_stmt.where(BidNoticeRecord.title.contains(q))

        total = (await session.execute(count_stmt)).scalar_one()
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "notices": rows,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "notice_type": notice_type,
            "q": q,
            "type_labels": NOTICE_TYPE_LABELS,
            "site_labels": SITE_LABELS,
        },
    )


@app.get("/detail/{notice_id}", response_class=HTMLResponse)
async def detail(request: Request, notice_id: int):
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(BidNoticeRecord).where(BidNoticeRecord.id == notice_id)
        record = (await session.execute(stmt)).scalar_one_or_none()

    if not record:
        return HTMLResponse("<h1>未找到</h1>", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={
            "n": record,
            "type_labels": NOTICE_TYPE_LABELS,
            "site_labels": SITE_LABELS,
        },
    )


@app.get("/pdf/{filename}")
async def serve_pdf(filename: str):
    path = _PDF_DIR / filename
    if not path.exists() or not path.name.endswith(".pdf"):
        return HTMLResponse("<h1>PDF未找到</h1>", status_code=404)
    return FileResponse(path, media_type="application/pdf")
