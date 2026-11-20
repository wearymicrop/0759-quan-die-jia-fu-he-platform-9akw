from collections import defaultdict

from app.manifest import sha, canonical
from app.modules.eligibility.compatibility import matrix
from app.modules.eligibility.qualification import evaluated
from app.modules.optimizer.solver import solve

# 差异来源口径（同 code 同含义，页面 reason 标签统一翻译）
ORPHAN_REASON = "SALE_MISSING"
BLOCKED_RETURN_REASON = "RETURN_CLAIM_BLOCKED"


def _settlement_id(digest, order_id):
    return sha(canonical(["settlement", digest, order_id]))[:16]


def _remaining_sale(sale, retained_qty):
    """用原票规则、剩余件数构造一份同口径小票，不改动原票分摊。"""
    return {
        "id": sale["id"],
        "at": sale["at"],
        "shop": sale["shop"],
        "source_line": sale["source_line"],
        "paid": None,
        "coupons": list(sale["chosen"]),
        "lines": [
            {"id": line["id"], "category": line["category"],
             "qty": retained_qty[line["id"]], "price": line["price"]}
            for line in sale["lines"] if retained_qty[line["id"]] > 0
        ],
    }


def _remaining_evaluation(sale, retained_qty, versions):
    """剩余可用组合：沿用原票时点的有效券版本重新判定资格并重算。"""
    remaining_lines = [line for line in sale["lines"] if retained_qty[line["id"]] > 0]
    if not remaining_lines:
        return {"basket_empty": True, "findings": [], "trials": [], "due": 0}
    synthetic = _remaining_sale(sale, retained_qty)
    qualification = evaluated(synthetic, versions)
    qualification["matrix"] = matrix(qualification["qualified"], versions["pairs"])
    solution = solve(synthetic, qualification)
    findings = [
        {"coupon": item["coupon"], "reason": item["reason"],
         "eligible_gross": item.get("eligible_gross", 0)}
        for item in qualification["findings"]
    ]
    return {"basket_empty": False, "findings": findings,
            "trials": solution.get("trials", []), "due": solution.get("due", 0)}


def _line_snapshot(sale, returns_by_line):
    snapshots = []
    for line in sale["lines"]:
        posted = [row for row in returns_by_line.get((sale["id"], line["id"]), [])
                  if row["status"] == "posted"]
        returned_qty = sum(row["qty"] for row in posted)
        refunded = sum(row["expected"] for row in posted)
        refunded_gross = sum(row["gross"] for row in posted)
        refunded_discount = sum(row["discount"] for row in posted)
        retained_qty = line["qty"] - returned_qty
        retained_gross = retained_qty * line["price"]
        retained_discount = line["discount"] - refunded_discount
        retained_net = retained_gross - retained_discount
        snapshots.append({
            "line": line["id"], "category": line["category"],
            "qty": line["qty"], "price": line["price"],
            "gross": line["gross"], "discount": line["discount"], "actual": line["actual"],
            "returned_qty": returned_qty, "retained_qty": retained_qty,
            "refunded": refunded, "refunded_gross": refunded_gross,
            "refunded_discount": refunded_discount,
            "retained_gross": retained_gross, "retained_discount": retained_discount,
            "retained_net": retained_net,
            "gap": line["actual"] - refunded - retained_net,
        })
    return snapshots


def _coupon_carry(sale, line_snapshots, remaining):
    """原组合各券在已退/剩余之间的承接，以及剩余口径门槛漂移。"""
    retained_discount = sum(row["retained_discount"] for row in line_snapshots)
    threshold = {
        item["coupon"]: item.get("eligible_gross", 0)
        for item in remaining.get("findings", [])
    }
    carry = []
    for applied in sale.get("applied", []):
        code = applied["code"]
        recheck = next((row for row in remaining.get("findings", []) if row["coupon"] == code), None)
        carry.append({
            "code": code, "version": applied["version"], "amount": applied["amount"],
            "shares": applied["shares"],
            "remaining_reason": recheck["reason"] if recheck else "BASKET_EMPTY",
            "remaining_eligible_gross": threshold.get(code, 0),
        })
    return carry, retained_discount


def _build_sheet(sale, returns, retained_qty, versions, digest, balance_rows):
    """balance_rows 为该原票在金额对账模块的逐行守恒结果。"""
    returns_by_line = defaultdict(list)
    for row in returns:
        returns_by_line[row["order"], row["line"]].append(row)
    line_snapshots = _line_snapshot(sale, returns_by_line)
    remaining = _remaining_evaluation(sale, retained_qty, versions)
    carry, retained_discount = _coupon_carry(sale, line_snapshots, remaining)

    posted = [row for row in returns if row["status"] == "posted"]
    blocked = [
        {"id": row["id"], "line": row["line"], "qty": row["qty"], "cash": row["cash"],
         "at": row["at"], "source_line": row["source_line"], "reason": row["reason"]}
        for row in returns if row["status"] == "isolated"
    ]
    totals = {
        "gross": sale["gross"], "discount": sale["discount"], "due": sale["due"], "paid": sale["paid"],
        "refunded": sum(row["expected"] for row in posted),
        "cash_refunded": sum(row["cash"] for row in posted),
        "retained_gross": sum(row["retained_gross"] for row in line_snapshots),
        "retained_discount": retained_discount,
        "retained_net": sum(row["retained_net"] for row in line_snapshots),
    }

    # 差异来源：结构性不平为硬阻断；实退现金差额为可发布差异，仅列示不改账。
    structural_gap = sum(row["gap"] for row in balance_rows)
    differences = [
        {"id": row["id"], "reason": "RETURN_CASH_GAP", "gap": row["cash_gap"],
         "source_line": row["source_line"], "expected": row["expected"], "cash": row["cash"]}
        for row in posted if row["cash_gap"]
    ]
    for row in carry:
        if row["remaining_reason"] == "MINIMUM_NOT_MET":
            differences.append({"id": sale["id"], "line": None,
                                "reason": "COUPON_THRESHOLD_DRIFT",
                                "gap": None, "coupon": row["code"],
                                "eligible_gross": row["remaining_eligible_gross"]})
    blocking = []
    imbalance = [{"line": row["line"], "gap": row["gap"]} for row in balance_rows if row["gap"]]
    if imbalance:
        blocking.append({"reason": "LINE_IMBALANCE", "lines": imbalance, "gap": structural_gap})
    if blocked:
        blocking.append({"reason": BLOCKED_RETURN_REASON, "claims": [row["id"] for row in blocked]})

    return {
        "id": _settlement_id(digest, sale["id"]),
        "order": sale["id"], "status": sale["status"],
        "source_line": sale["source_line"], "at": sale["at"], "shop": sale["shop"],
        "sale_day": posted[0]["sale_day"] if posted else None,
        "original": {"chosen": sale["chosen"], "applied": sale.get("applied", []),
                     "gross": sale["gross"], "discount": sale["discount"],
                     "due": sale["due"], "paid": sale["paid"]},
        "lines": line_snapshots,
        "returns": [
            {"id": row["id"], "line": row["line"], "qty": row["qty"], "at": row["at"],
             "source_line": row["source_line"], "original_line": row["original_line"],
             "gross": row["gross"], "discount": row["discount"], "expected": row["expected"],
             "cash": row["cash"], "cash_gap": row["cash_gap"],
             "return_day": row["return_day"], "returned_qty": row["returned_qty"]}
            for row in posted
        ],
        "blocked_returns": blocked,
        "remaining": remaining,
        "coupon_carry": carry,
        "totals": totals,
        "differences": differences,
        "blocking": blocking,
        "publishable": not blocking,
    }


def build_settlement(sales, returns, reconcile, versions, digest):
    """按原票逐单形成唯一复核单；无原票退货单独留痕，不并入任何单。"""
    retained_qty = defaultdict(dict)
    posted_counts = defaultdict(int)
    for row in returns:
        if row["status"] == "posted":
            posted_counts[row["order"], row["line"]] += row["qty"]
    for sale in sales:
        for line in sale.get("lines", []):
            retained_qty[sale["id"]][line["id"]] = line["qty"] - posted_counts[sale["id"], line["id"]]

    balance_by_order = defaultdict(list)
    for row in reconcile["lines"]:
        balance_by_order[row["order"]].append(row)
    returns_by_order = defaultdict(list)
    for row in returns:
        returns_by_order[row["order"]].append(row)

    sheets = []
    for sale in sales:
        if sale["id"] not in returns_by_order:
            continue
        if sale["status"] != "solved":
            # 缺有效原票口径：不形成可发布复核单，但退货全部留痕并给出阻断原因。
            blocked = [
                {"id": row["id"], "line": row["line"], "qty": row["qty"], "cash": row["cash"],
                 "at": row["at"], "source_line": row["source_line"],
                 "reason": row["reason"] if row["status"] == "isolated" else "SALE_ISOLATED"}
                for row in returns_by_order[sale["id"]]
            ]
            sheets.append({
                "id": _settlement_id(digest, sale["id"]), "order": sale["id"],
                "status": sale["status"], "reason": sale.get("reason", "SALE_ISOLATED"),
                "source_line": sale.get("source_line"), "at": sale.get("at"),
                "shop": sale.get("shop"), "sale_day": None,
                "original": None, "lines": [], "returns": [], "blocked_returns": blocked,
                "remaining": {"basket_empty": True, "findings": [], "trials": [], "due": 0},
                "coupon_carry": [], "totals": {}, "differences": [],
                "blocking": [{"reason": "SALE_ISOLATED", "claims": [row["id"] for row in blocked]}],
                "publishable": False,
            })
            continue
        sheet = _build_sheet(
            sale, returns_by_order[sale["id"]], retained_qty[sale["id"]], versions, digest,
            balance_by_order.get(sale["id"], []),
        )
        sheets.append(sheet)

    solved_orders = {sale["id"] for sale in sales}
    orphan_returns = [
        {"id": row["id"], "order": row["order"], "line": row["line"], "qty": row["qty"],
         "cash": row["cash"], "at": row["at"], "source_line": row["source_line"],
         "reason": ORPHAN_REASON}
        for row in returns if row["order"] not in solved_orders
    ]
    sheets.sort(key=lambda sheet: sheet["order"])
    publishable = all(sheet["publishable"] for sheet in sheets) and not orphan_returns
    return {
        "digest": digest,
        "sheets": sheets,
        "orphan_returns": orphan_returns,
        "publishable": publishable,
        "blocked_count": sum(1 for sheet in sheets if not sheet["publishable"]),
    }
