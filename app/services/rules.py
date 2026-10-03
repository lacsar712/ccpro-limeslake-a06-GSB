"""石灰熟化池业务规则。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import Pond, ReagentVoucher, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def _as_aware(dt: datetime) -> datetime:
    """表单提交的无时域时间按 UTC 处理，保证可与带时区列比较。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def sorted_vouchers(batch: SlakeBatch) -> list[ReagentVoucher]:
    return sorted(batch.vouchers, key=lambda v: v.voucher_no)


def next_voucher_no(batch: SlakeBatch) -> int:
    if not batch.vouchers:
        return 1
    return max(v.voucher_no for v in batch.vouchers) + 1


def voucher_chain_status(batch: SlakeBatch) -> tuple[bool, str]:
    """
    峰值登记前的投放凭门槛：
    1) 至少 1 条投放凭；
    2) 凭号从 1 起连续、不重复；
    3) 最近一次投放时刻晚于批次开班时刻。
    """
    vouchers = sorted_vouchers(batch)
    if not vouchers:
        return False, "该批次尚无熟化剂投放凭，投放凭未齐，不能登记或改写峰值温度"

    numbers = [v.voucher_no for v in vouchers]
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        return (
            False,
            f"投放凭凭号须从 1 起连续（应为 {expected}，实际为 {numbers}），投放凭未齐，不能登记峰值温度",
        )

    latest = max(vouchers, key=lambda v: _as_aware(v.dispensed_at))
    if _as_aware(latest.dispensed_at) <= _as_aware(batch.started_at):
        return (
            False,
            "最近一次熟化剂投放时刻不晚于开班时刻，投放凭未齐，不能登记峰值温度",
        )

    return True, ""


def assert_vouchers_ready_for_peak(batch: SlakeBatch) -> None:
    ok, msg = voucher_chain_status(batch)
    if not ok:
        raise RuleError(msg)


def set_batch_peak_temp(batch: SlakeBatch, peak_temp_c: float) -> None:
    """写入或改写峰值温度的统一入口：先卡投放凭门槛。"""
    assert_vouchers_ready_for_peak(batch)
    batch.peak_temp_c = peak_temp_c


def assert_can_add_voucher(
    batch: SlakeBatch,
    voucher_no: int,
    amount_kg: float,
) -> None:
    """登记投放凭的前提：仅熟化中批次可写、凭号不重复、投放公斤数为正。"""
    pond = batch.pond
    if pond is None or pond.status != Pond.STATUS_SLAKING:
        status_label = {
            Pond.STATUS_FILLING: "注水中",
            Pond.STATUS_SLAKING: "熟化中",
            Pond.STATUS_DRAWN: "已出灰",
        }.get(pond.status if pond else "", pond.status if pond else "未知")
        raise RuleError(f"仅熟化中批次可登记投放凭，该池当前状态为「{status_label}」")

    if voucher_no < 1:
        raise RuleError("凭号须从 1 起的正整数")
    if amount_kg <= 0:
        raise RuleError("投放公斤数须为正数")
    if any(v.voucher_no == voucher_no for v in batch.vouchers):
        raise RuleError(f"凭号 {voucher_no} 在本批次已存在，同批次凭号不得重复")


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
    """
    latest = latest_batch_for_pond(pond)
    if latest is None:
        return False, "该池尚无熟化批次，不能标记为已出灰"
    if latest.peak_temp_c is None:
        return False, "最近批次尚未记录峰值温度，不能标记为已出灰"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近批次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出灰",
        )
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)
