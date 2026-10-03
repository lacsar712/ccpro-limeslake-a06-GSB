"""熟化剂投放凭：按批次展示凭链并登记新凭。"""

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import DosingVoucher, Pond, SlakeBatch
from app.services.rules import (
    RuleError,
    assert_can_add_voucher,
    next_voucher_no,
    vouchers_for_batch,
)

bp = Blueprint("vouchers", __name__, url_prefix="/vouchers")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def _redirect_back(batch: SlakeBatch):
    """抽屉内提交时回到平面图并保持抽屉打开；否则留在投放凭专页。"""
    nxt = (request.form.get("next") or "").strip()
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("vouchers.list_vouchers", batch_id=batch.id))


def _all_batches() -> list[SlakeBatch]:
    return (
        SlakeBatch.query.join(Pond)
        .order_by(SlakeBatch.started_at.desc())
        .all()
    )


@bp.route("/")
@login_required
def list_vouchers():
    batches = _all_batches()
    selected_id = request.args.get("batch_id", type=int)
    selected = next((b for b in batches if b.id == selected_id), None)
    if selected is None and batches:
        slaking = [b for b in batches if b.pond.status == Pond.STATUS_SLAKING]
        selected = slaking[0] if slaking else batches[0]

    vouchers = vouchers_for_batch(selected) if selected else []
    suggested_no = next_voucher_no(selected) if selected else 1
    return render_template(
        "vouchers/list.html",
        batches=batches,
        selected=selected,
        vouchers=vouchers,
        suggested_no=suggested_no,
        status_labels=STATUS_LABELS,
    )


@bp.route("/add", methods=["POST"])
@login_required
def add_voucher():
    batch_id = request.form.get("batch_id", type=int)
    batch = db.session.get(SlakeBatch, batch_id) if batch_id else None
    if batch is None:
        flash("请选择熟化批次", "error")
        return redirect(url_for("vouchers.list_vouchers"))

    def fail(message: str):
        db.session.rollback()
        flash(message, "error")
        return _redirect_back(batch)

    reagent = (request.form.get("reagent_name") or "").strip()
    operator = (request.form.get("operator") or "").strip() or current_user.username
    dosed_raw = (request.form.get("dosed_at") or "").strip()

    try:
        voucher_no = int(request.form.get("voucher_no"))
    except (TypeError, ValueError):
        return fail("凭号须为不小于 1 的整数")

    try:
        dose_kg = float(request.form.get("dose_kg"))
    except (TypeError, ValueError):
        return fail("投放公斤数须为正数")

    if not reagent:
        return fail("药剂名不能为空")
    try:
        dosed_at = datetime.fromisoformat(dosed_raw) if dosed_raw else datetime.utcnow()
    except ValueError:
        return fail("投放时刻格式无效")

    try:
        assert_can_add_voucher(batch, voucher_no, dose_kg)
    except RuleError as exc:
        return fail(str(exc))

    voucher = DosingVoucher(
        batch=batch,
        voucher_no=voucher_no,
        reagent_name=reagent,
        dose_kg=dose_kg,
        dosed_at=dosed_at,
        operator=operator,
    )
    db.session.add(voucher)
    try:
        db.session.commit()
    except IntegrityError:
        # 两名操作工并发交同一凭号：唯一约束兜底，只许落一笔。
        return fail(f"凭号 {voucher_no} 已被登记，同批次凭号不得重复")
    flash(f"投放凭 #{voucher_no} 已登记", "ok")
    return _redirect_back(batch)
