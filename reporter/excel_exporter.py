from pathlib import Path
from typing import Iterable, Mapping

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


def shorten_text(text: str, max_len: int = 42) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def save_listing_table(rows: Iterable[Mapping], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "搜索结果"

    headers = ["序号", "标题", "价格", "商品链接", "完整标题"]
    ws.append(headers)

    sorted_rows = sorted(
        rows,
        key=lambda row: (float(row.get("price") or 0) <= 0, float(row.get("price") or 0)),
    )
    if sorted_rows:
        for index, row in enumerate(sorted_rows, start=1):
            title = str(row.get("title", ""))
            ws.append([
                index,
                shorten_text(title),
                row.get("price", ""),
                row.get("url", ""),
                title,
            ])
    else:
        ws.append([1, "无匹配商品", "", "", "本次搜索未采集到符合标题规则的商品"])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    widths = {
        "A": 8,
        "B": 44,
        "C": 12,
        "D": 64,
        "E": 80,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    for row in ws.iter_rows(min_row=2):
        row[0].alignment = Alignment(horizontal="center", vertical="top")
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[2].alignment = Alignment(horizontal="right", vertical="top")
        row[3].alignment = Alignment(wrap_text=True, vertical="top")
        row[4].alignment = Alignment(wrap_text=True, vertical="top")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    if ws.max_row >= 2:
        table_ref = f"A1:E{ws.max_row}"
        table = Table(displayName="SearchResults", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(table)

    wb.save(path)
    return path
