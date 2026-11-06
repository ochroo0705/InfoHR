"""The chart as an Excel file: the chart's numbers in a small table and a native Excel chart (bar or pie) drawn from
them, so the user can restyle it in Excel. Built from the same ChartData as the on-screen chart."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList

from assistant.chart_data import ChartData

SHEET = "График"
MAX_SHEET_TITLE = 120


def chart_workbook(data: ChartData) -> bytes:
    """The workbook bytes: header row, one row per group (label, people, share in percent), and the chart beside it."""
    wb = Workbook()
    ws = wb.create_sheet(SHEET)
    default = wb.active
    assert default is not None
    wb.remove(default)  # the empty sheet every new workbook starts with
    ws.append([data.by_label, "Хүн", "Хувь (%)"])
    for label, count in zip(data.labels, data.counts, strict=True):
        ws.append([label, count, round(count * 100 / data.total, 1) if data.total else 0])
        cell = ws.cell(row=ws.max_row, column=1)
        cell.data_type = "s"  # always text: openpyxl would turn a label that starts with «=» into a formula
    ws.append(["Нийт", data.total, 100 if data.total else 0])
    ws.column_dimensions["A"].width = 32
    rows = len(data.labels)
    title = f"{data.by_label}: нийт {data.total} хүн"[:MAX_SHEET_TITLE]
    values = Reference(ws, min_col=2, min_row=1, max_row=1 + rows)
    labels = Reference(ws, min_col=1, min_row=2, max_row=1 + rows)
    chart: BarChart | PieChart
    if data.kind == "pie":
        chart = PieChart()
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showPercent = True
    else:
        chart = BarChart()
        horizontal = len(data.labels) > 6 or max((len(x) for x in data.labels), default=0) > 14
        chart.type = "bar" if horizontal else "col"
        if horizontal:
            chart.x_axis.scaling.orientation = "maxMin"  # the biggest group on top, as on screen
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showVal = True
        chart.legend = None
        chart.y_axis.majorUnit = 1 if max(data.counts, default=0) <= 10 else None
        chart.y_axis.delete = False
        chart.x_axis.delete = False
    chart.title = title
    chart.add_data(values, titles_from_data=True)
    chart.set_categories(labels)
    chart.width, chart.height = 22, 12
    ws.add_chart(chart, "E2")
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
