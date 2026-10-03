from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond
from app.services.rules import (
    RuleError,
    assert_can_set_pond_status,
    latest_batch_for_pond,
    set_batch_peak_temp,
    voucher_chain_status,
)

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


@bp.route("/")
@login_required
def floor_plan():
    plants = Plant.query.order_by(Plant.name).all()
    plant_id_raw = request.args.get("plant_id", "").strip()
    active_plant = None
    if plant_id_raw.isdigit():
        active_plant = db.session.get(Plant, int(plant_id_raw))
    if active_plant is None and plants:
        active_plant = plants[0]

    ponds = []
    if active_plant:
        ponds = (
            Pond.query.filter_by(plant_id=active_plant.id)
            .order_by(Pond.code)
            .all()
        )

    pond_cards = []
    for pond in ponds:
        batch = latest_batch_for_pond(pond)
        voucher_count = len(batch.vouchers) if batch is not None else 0
        pond_cards.append(
            {"pond": pond, "batch": batch, "voucher_count": voucher_count}
        )

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    selected_vouchers = []
    selected_chain_ok = True
    selected_chain_msg = ""
    if selected_id:
        selected = next((c["pond"] for c in pond_cards if c["pond"].id == selected_id), None)
        if selected:
            selected_batch = latest_batch_for_pond(selected)
            if selected_batch is not None:
                selected_vouchers = sorted(
                    selected_batch.vouchers, key=lambda v: v.voucher_no
                )
                selected_chain_ok, selected_chain_msg = voucher_chain_status(
                    selected_batch
                )

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        selected=selected,
        selected_batch=selected_batch,
        selected_vouchers=selected_vouchers,
        selected_chain_ok=selected_chain_ok,
        selected_chain_msg=selected_chain_msg,
        status_labels=STATUS_LABELS,
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    pond = Pond.query.get_or_404(pond_id)
    status = request.form.get("status") or pond.status
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()

    batch = latest_batch_for_pond(pond)
    if batch is None:
        flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    if peak_raw:
        try:
            peak_value = float(peak_raw)
        except ValueError:
            flash("峰值温度格式无效", "error")
            return redirect(
                url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
            )
    else:
        peak_value = None

    try:
        if peak_value is not None:
            set_batch_peak_temp(batch, peak_value)
        batch.notes = notes
        assert_can_set_pond_status(pond, status)
        pond.status = status
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id))
