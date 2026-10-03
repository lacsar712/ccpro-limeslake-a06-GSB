from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Pond, SlakeBatch
from app.services.rules import RuleError, set_batch_peak_temp

bp = Blueprint("batches", __name__, url_prefix="/batches")


def _parse_float(raw: str, field: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise RuleError(f"{field}格式无效")


@bp.route("/")
@login_required
def list_batches():
    batches = (
        SlakeBatch.query.join(Pond)
        .order_by(SlakeBatch.started_at.desc())
        .all()
    )
    return render_template("batches/list.html", batches=batches)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_batch():
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        pond = db.session.get(Pond, pond_id)
        if pond is None:
            flash("熟化池不存在", "error")
            return render_template("batches/form.html", ponds=ponds, batch=None)
        started_raw = request.form.get("started_at") or ""
        peak_raw = (request.form.get("peak_temp_c") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        try:
            target = _parse_float(request.form.get("target_temp_c") or 80, "目标温度")
            peak = _parse_float(peak_raw, "峰值温度") if peak_raw else None
            started_at = (
                datetime.fromisoformat(started_raw)
                if started_raw
                else datetime.utcnow()
            )
            batch = SlakeBatch(
                pond=pond,
                started_at=started_at,
                target_temp_c=target,
                notes=notes,
            )
            # 峰值写入统一走规则层：投放凭未齐一律拒绝，新批次绝无旁路上峰值。
            if peak is not None:
                set_batch_peak_temp(batch, peak)
            db.session.add(batch)
            db.session.commit()
            flash("熟化批次已登记", "ok")
        except RuleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template("batches/form.html", ponds=ponds, batch=None)
        return redirect(
            url_for(
                "board.floor_plan",
                plant_id=pond.plant_id,
                pond=pond_id,
            )
        )
    return render_template("batches/form.html", ponds=ponds, batch=None)


@bp.route("/<int:batch_id>/edit", methods=["GET", "POST"])
@login_required
def edit_batch(batch_id: int):
    batch = SlakeBatch.query.get_or_404(batch_id)
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        pond = db.session.get(Pond, pond_id)
        if pond is None:
            flash("熟化池不存在", "error")
            return render_template("batches/form.html", ponds=ponds, batch=batch)
        started_raw = request.form.get("started_at") or ""
        peak_raw = (request.form.get("peak_temp_c") or "").strip()
        try:
            batch.target_temp_c = _parse_float(
                request.form.get("target_temp_c") or 80, "目标温度"
            )
            peak = _parse_float(peak_raw, "峰值温度") if peak_raw else None
            if started_raw:
                batch.started_at = datetime.fromisoformat(started_raw)
            batch.notes = (request.form.get("notes") or "").strip()
            batch.pond = pond
            # 与平面图抽屉同一道门槛：投放凭未齐不得写入或改写峰值。
            if peak is not None:
                set_batch_peak_temp(batch, peak)
            else:
                batch.peak_temp_c = None
            db.session.commit()
            flash("熟化批次已更新", "ok")
        except RuleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template("batches/form.html", ponds=ponds, batch=batch)
        return redirect(
            url_for(
                "board.floor_plan",
                plant_id=pond.plant_id,
                pond=pond_id,
            )
        )
    return render_template("batches/form.html", ponds=ponds, batch=batch)
