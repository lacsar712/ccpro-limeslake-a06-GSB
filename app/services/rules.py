"""石灰熟化池业务规则。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import DosingVoucher, Pond, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def vouchers_for_batch(batch: SlakeBatch) -> list[DosingVoucher]:
    """按凭号升序返回该批次的投放凭。"""
    return sorted(batch.vouchers, key=lambda v: v.voucher_no)


def next_voucher_no(batch: SlakeBatch) -> int:
    existing = vouchers_for_batch(batch)
    if not existing:
        return 1
    return existing[-1].voucher_no + 1


def _as_naive(dt: datetime | None) -> datetime | None:
    """统一转成 naive UTC，避免 aware/naive 混存时比较报错。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def can_add_voucher(batch: SlakeBatch) -> tuple[bool, str]:
    """仅熟化中批次可写投放凭；已出灰批次禁止再写凭。"""
    if batch.pond is None:
        return False, "该批次未关联熟化池，不能登记投放凭"
    if batch.pond.status != Pond.STATUS_SLAKING:
        return False, "仅熟化中批次可登记投放凭，已出灰或非熟化中批次禁止写凭"
    return True, ""


def assert_can_add_voucher(batch: SlakeBatch, voucher_no: int, dose_kg: float) -> None:
    ok, msg = can_add_voucher(batch)
    if not ok:
        raise RuleError(msg)
    if not isinstance(voucher_no, int) or voucher_no < 1:
        raise RuleError("凭号须为不小于 1 的整数")
    if dose_kg is None or dose_kg <= 0:
        raise RuleError("投放公斤数须为正数")
    if any(v.voucher_no == voucher_no for v in batch.vouchers):
        raise RuleError(f"凭号 {voucher_no} 在本批次已存在，同批次凭号不得重复")


def voucher_chain_status(batch: SlakeBatch) -> tuple[bool, str]:
    """
    写峰值前投放凭须齐全：
    至少 1 条、凭号自 1 起连续、最近一次投放晚于开班时刻。
    """
    vouchers = vouchers_for_batch(batch)
    if not vouchers:
        return False, "本批次尚无熟化剂投放凭，缺凭不能写入峰值"
    numbers = [v.voucher_no for v in vouchers]
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        return False, (
            f"投放凭凭号不连续（现有 {numbers}，应为自 1 起连续），补齐前不能写入峰值"
        )
    latest = max(vouchers, key=lambda v: _as_naive(v.dosed_at))
    if _as_naive(latest.dosed_at) <= _as_naive(batch.started_at):
        return False, "最近一次熟化剂投放不晚于开班时刻，凭链无效，不能写入峰值"
    return True, ""


def can_write_peak(batch: SlakeBatch) -> tuple[bool, str]:
    """
    熟化中批次要写入或改写峰值前，须有匹配且齐全的熟化剂投放凭。
    非熟化中批次（注水中/已出灰）不设投放凭门槛。
    """
    if batch.pond is not None and batch.pond.status == Pond.STATUS_SLAKING:
        return voucher_chain_status(batch)
    return True, ""


def assert_can_write_peak(batch: SlakeBatch) -> None:
    ok, msg = can_write_peak(batch)
    if not ok:
        raise RuleError(msg)


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃；
    且该批次熟化剂投放凭链齐全（防止不经熟化直接出灰的旁路）。
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
    # 已出灰池保持已出灰（只改容量等）时不再重复要求凭链；
    # 凡实际转入出灰，投放凭门槛与旧规一起卡。
    if pond.status != Pond.STATUS_DRAWN:
        ok, msg = voucher_chain_status(latest)
        if not ok:
            return False, msg
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)
