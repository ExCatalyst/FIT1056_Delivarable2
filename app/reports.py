"""Reporting (F-06). Reports contain stock data only - no client personal information (FR-REP-03)."""
import csv
import io
from collections import defaultdict
from typing import Dict, List

from .models import StockMovement, User
from .security import require, resolve_site
from .validators import parse_date


class ReportService:
    def __init__(self, ctx):
        self.ctx = ctx

    def _movements(self, actor: User, start, end, site_id):
        actor = self.ctx.refresh(actor)
        require(actor, "report.view")  # volunteers, donors and clients are denied
        site = resolve_site(actor, site_id)
        start_d, end_d = parse_date(start, "start"), parse_date(end, "end")
        if end_d < start_d:
            from .errors import ValidationError
            raise ValidationError("Invalid date range.", {"end": "End date must not be before the start date."})
        rows = []
        for raw in self.ctx.store.data["movements"]:
            m = StockMovement.from_dict(raw)
            day = parse_date(m.timestamp[:10])
            if start_d <= day <= end_d and (not site or m.site_id == site):
                rows.append(m)
        return rows, site

    def stock_movement_report(self, actor: User, start, end, site_id: str = None) -> Dict:
        """FR-REP-01: stock received vs distributed per item for a date range and site."""
        moves, site = self._movements(actor, start, end, site_id)
        agg: Dict[str, Dict] = {}
        for m in moves:
            row = agg.setdefault(m.item_name.lower(), {"item": m.item_name, "received": 0, "distributed": 0})
            if m.delta > 0:
                row["received"] += m.delta
            else:
                row["distributed"] += -m.delta
        rows = sorted(agg.values(), key=lambda r: r["item"].lower())
        for r in rows:
            r["net"] = r["received"] - r["distributed"]
        return {"site_id": site or "ALL", "start": str(start), "end": str(end), "rows": rows,
                "totals": {"received": sum(r["received"] for r in rows),
                           "distributed": sum(r["distributed"] for r in rows)}}

    def demand_trend_report(self, actor: User, start, end, site_id: str = None, bucket: str = "week") -> Dict:
        """FR-REP-01: how much of each item was distributed per week/month."""
        moves, site = self._movements(actor, start, end, site_id)
        agg = defaultdict(int)
        for m in moves:
            if m.delta < 0:
                day = parse_date(m.timestamp[:10])
                if bucket == "month":
                    period = day.strftime("%Y-%m")
                else:
                    iso = day.isocalendar()
                    period = f"{iso[0]}-W{iso[1]:02d}"
                agg[(period, m.item_name)] += -m.delta
        rows = [{"period": p, "item": i, "distributed": q} for (p, i), q in sorted(agg.items())]
        return {"site_id": site or "ALL", "bucket": bucket, "rows": rows}

    @staticmethod
    def to_csv(rows: List[Dict], columns: List[str]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()
