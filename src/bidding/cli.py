import asyncio
from typing import Optional

import structlog
import typer

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

app = typer.Typer(name="bidding", help="招标信息智能采集系统")


@app.command()
def scrape(
    site: Optional[list[str]] = typer.Option(None, "--site", "-s", help="站点名称"),
    max_pages: int = typer.Option(50, "--max-pages", "-p", help="最大翻页数"),
    headless: bool = typer.Option(True, "--headless/--headed", help="无头/有头模式"),
    stop_after: int = typer.Option(10, "--stop-after", help="连续重复N条后停止"),
):
    """采集招标信息"""
    from bidding.core.engine import ScrapingEngine

    engine = ScrapingEngine(
        headless=headless,
        max_pages=max_pages,
        incremental_stop=stop_after,
    )
    asyncio.run(engine.run(site_names=site))
    typer.echo(f"\n采集完成，共保存 {engine.pipeline.saved_count} 条记录")


@app.command("list-sites")
def list_sites():
    """列出所有已注册的站点适配器"""
    from bidding.adapters.registry import auto_discover, list_adapters

    auto_discover()
    adapters = list_adapters()
    if not adapters:
        typer.echo("没有已注册的适配器")
        return
    typer.echo(f"已注册 {len(adapters)} 个站点适配器:\n")
    for name, cls in adapters.items():
        meta = cls.meta
        login = "需登录" if meta.requires_login else "公开"
        types = ", ".join(t.value for t in meta.notice_types)
        typer.echo(f"  {name:15s} {meta.display_name:10s} [{login}]  {meta.base_url}")
        typer.echo(f"  {'':15s} 公告类型: {types}")
        typer.echo()


@app.command()
def stats():
    """显示采集统计"""
    from bidding.storage.database import init_db
    from bidding.storage.repository import NoticeRepository

    async def _stats():
        await init_db()
        repo = NoticeRepository()
        total = await repo.count()
        typer.echo(f"数据库中共有 {total} 条记录")

    asyncio.run(_stats())


@app.command()
def web(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="端口"),
):
    """启动Web展示页面"""
    import uvicorn

    typer.echo(f"启动Web服务: http://localhost:{port}")
    uvicorn.run("bidding.web.app:app", host=host, port=port, reload=True)


@app.command("fetch-details")
def fetch_details(
    site: Optional[list[str]] = typer.Option(None, "--site", "-s", help="站点名称"),
    limit: int = typer.Option(50, "--limit", "-n", help="最多采集几条"),
    headless: bool = typer.Option(True, "--headless/--headed", help="无头/有头模式"),
):
    """补采已有记录的详情页正文"""
    from bidding.core.detail_fetcher import DetailFetcher

    fetcher = DetailFetcher(headless=headless, limit=limit)
    asyncio.run(fetcher.run(site_names=site))
    typer.echo(f"\n详情采集完成，共更新 {fetcher.updated_count} 条记录")


@app.command("fetch-pdf")
def fetch_pdf(
    site: Optional[list[str]] = typer.Option(None, "--site", "-s", help="站点名称"),
    limit: int = typer.Option(50, "--limit", "-n", help="最多处理几条"),
):
    """从PDF附件提取公告正文（用于大唐等提供PDF链接的站点）"""
    from bidding.core.pdf_fetcher import PdfFetcher

    fetcher = PdfFetcher(limit=limit)
    asyncio.run(fetcher.run(site_names=site))
    typer.echo(f"\nPDF正文提取完成，共更新 {fetcher.updated_count} 条记录")


if __name__ == "__main__":
    app()
