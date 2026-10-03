from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Pond, ReagentVoucher, SlakeBatch, utcnow
from app.services.rules import (
    RuleError,
    assert_can_add_voucher,
    next_voucher_no,
    sorted_vouchers,
    voucher_chain_status,
)

bp = Blueprint("vouchers", __name__, url_prefix="/vouchers")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def _all_batches() -> list[SlakeBatch]:
    return (
        SlakeBatch.query.join(Pond)
        .order_by(SlakeBatch.started_at.desc())
        .all()
    )


@bp.route("/")
@login_required
def index():
    batches = _all_batches()
    selected_id = request.args.get("batch_id", type=int)
    selected = None
    if selected_id:
        selected = db.session.get(SlakeBatch, selected_id)

    chain_ok = True
    chain_msg = ""
    if selected is not None:
        chain_ok, chain_msg = voucher_chain_status(selected)

    return render_template(
        "vouchers/index.html",
        batches=batches,
        selected=selected,
        selected_vouchers=sorted_vouchers(selected) if selected else [],
        next_no=next_voucher_no(selected) if selected else 1,
        chain_ok=chain_ok,
        chain_msg=chain_msg,
        status_labels=STATUS_LABELS,
        can_write=bool(
            selected and selected.pond and selected.pond.status == Pond.STATUS_SLAKING
        ),
    )


@bp.route("/batches/<int:batch_id>/add", methods=["POST"])
@login_required
def add_voucher(batch_id: int):
    batch = SlakeBatch.query.get_or_404(batch_id)
    redirect_url = url_for("vouchers.index", batch_id=batch.id)

    try:
        try:
            voucher_no = int((request.form.get("voucher_no") or "").strip())
        except ValueError:
            raise RuleError("凭号须为从 1 起的整数")

        reagent_name = (request.form.get("reagent_name") or "").strip()
        if not reagent_name:
            raise RuleError("药剂名不能为空")

        try:
            amount_kg = float((request.form.get("amount_kg") or "").strip())
        except ValueError:
            raise RuleError("投放公斤数格式无效，须为正数")

        dispensed_raw = (request.form.get("dispensed_at") or "").strip()
        if dispensed_raw:
            try:
                dispensed_at = datetime.fromisoformat(dispensed_raw)
            except ValueError:
                raise RuleError("投放时刻格式无效")
            if dispensed_at.tzinfo is None:
                dispensed_at = dispensed_at.replace(tzinfo=timezone.utc)
        else:
            dispensed_at = utcnow()

        dispensed_by = (request.form.get("dispensed_by") or "").strip() or (
            current_user.username if current_user.is_authenticated else ""
        )
        if not dispensed_by:
            raise RuleError("投放人不能为空")

        # 规则层：仅熟化中、凭号不重复、公斤数为正。
        assert_can_add_voucher(batch, voucher_no, amount_kg)

        voucher = ReagentVoucher(
            batch=batch,
            voucher_no=voucher_no,
            reagent_name=reagent_name,
            amount_kg=amount_kg,
            dispensed_at=dispensed_at,
            dispensed_by=dispensed_by,
        )
        db.session.add(voucher)
        try:
            # 同批次凭号唯一约束兜底并发：两名操作工抢同一凭号，只落一笔。
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                f"凭号 {voucher_no} 已被其他操作工抢先登记，同批次凭号不得重复，本笔投放凭未写入",
                "error",
            )
            return redirect(redirect_url)
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(redirect_url)

    flash(f"投放凭 #{voucher_no} 已登记", "ok")
    return redirect(redirect_url)
