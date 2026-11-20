from app.errors import DomainError
from app.store import fetch, fetch_settlement, list_settlements, publish_settlement


def _sheet(run, settlement_id):
    for sheet in run["result"]["settlement"]["sheets"]:
        if sheet["id"] == settlement_id:
            return sheet
    raise DomainError("SETTLEMENT_NOT_FOUND", "找不到该复核单", 404)


def publish(run_id, settlement_id):
    """发布闸门：缺原票、原单隔离、对账不平、退货被阻断者一律拒绝。"""
    _, run = fetch(run_id)
    sheet = _sheet(run, settlement_id)
    if not sheet["publishable"]:
        reasons = [item["reason"] for item in sheet["blocking"]]
        raise DomainError("SETTLEMENT_NOT_PUBLISHABLE",
                          f"复核单 {sheet['order']} 不满足发布条件：{'、'.join(reasons)}", 422)
    record = {**sheet, "run_id": run_id, "published": True}
    return publish_settlement(run_id, record)


def published(run_id, settlement_id):
    return fetch_settlement(run_id, settlement_id)


def published_all(run_id):
    # 校验批次存在，缺批次直接 404。
    fetch(run_id)
    return {"run_id": run_id, "settlements": list_settlements(run_id)}
