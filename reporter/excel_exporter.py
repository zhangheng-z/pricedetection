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
    rows = list(rows)
    include_judgment = any(row.get("judgment") for row in rows)

    wb = Workbook()
    ws = wb.active
    ws.title = "\u641c\u7d22\u7ed3\u679c"

    headers = ["\u5e8f\u53f7", "\u6807\u9898", "\u4ef7\u683c", "\u5546\u54c1\u94fe\u63a5", "\u5b8c\u6574\u6807\u9898"]
    if include_judgment:
        headers.append("\u5224\u5b9a\u7ed3\u679c")
    ws.append(headers)

    sorted_rows = sorted(
        rows,
        key=lambda row: (float(row.get("price") or 0) <= 0, float(row.get("price") or 0)),
    )
    if sorted_rows:
        for index, row in enumerate(sorted_rows, start=1):
            title = str(row.get("title", ""))
            values = [
                index,
                shorten_text(title),
                row.get("price", ""),
                row.get("url", ""),
                title,
            ]
            if include_judgment:
                values.append(row.get("judgment", ""))
            ws.append(values)
    else:
        values = [
            1,
            "\u65e0\u5339\u914d\u5546\u54c1",
            "",
            "",
            "\u672c\u6b21\u641c\u7d22\u672a\u91c7\u96c6\u5230\u7b26\u5408\u6807\u9898\u89c4\u5219\u7684\u5546\u54c1",
        ]
        if include_judgment:
            values.append("")
        ws.append(values)

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
    if include_judgment:
        widths["F"] = 16
    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    for row in ws.iter_rows(min_row=2):
        row[0].alignment = Alignment(horizontal="center", vertical="top")
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[2].alignment = Alignment(horizontal="right", vertical="top")
        row[3].alignment = Alignment(wrap_text=True, vertical="top")
        row[4].alignment = Alignment(wrap_text=True, vertical="top")
        if include_judgment and len(row) >= 6:
            row[5].alignment = Alignment(horizontal="center", vertical="top")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    if ws.max_row >= 2:
        table_ref = f"A1:{'F' if include_judgment else 'E'}{ws.max_row}"
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
