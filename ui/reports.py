"""Date/site reporting with CSV downloads and no client profile exports."""
from datetime import date, timedelta

import streamlit as st

from ui.common import site_filter, table


def show(app, user):
    """Generate stock and demand reports through the reporting service."""
    st.title("Reports")
    st.caption("Reports contain food stock and distribution totals, without client personal details.")
    site = site_filter(user, "report_site")
    columns = st.columns(2)
    start = columns[0].date_input("Start date", value=date.today() - timedelta(days=30))
    end = columns[1].date_input("End date", value=date.today())
    if end < start:
        st.error("Choose an end date on or after the start date.")
        return
    kind = st.radio("Report type", ["Stock movements", "Demand trends"], horizontal=True)
    if kind == "Stock movements":
        report = app.reports.stock_movement_report(user, start, end, site_id=site)
        columns = st.columns(2)
        columns[0].metric("Received units", report["totals"]["received"])
        columns[1].metric("Distributed units", report["totals"]["distributed"])
        table(report["rows"], "No stock movements were recorded in this period.")
        columns = ["item", "received", "distributed", "net"]
        filename = "stock-movements.csv"
    else:
        bucket = st.selectbox("Group by", ["week", "month"])
        report = app.reports.demand_trend_report(user, start, end, site_id=site, bucket=bucket)
        table(report["rows"], "No food distributions were recorded in this period.")
        columns = ["period", "item", "distributed"]
        filename = "demand-trends.csv"
    if report["rows"]:
        csv = app.reports.to_csv(report["rows"], columns)
        st.download_button("Download report as CSV", data=csv, file_name=filename, mime="text/csv")
