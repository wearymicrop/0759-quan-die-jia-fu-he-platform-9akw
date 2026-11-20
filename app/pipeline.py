from app.manifest import canonical, sha
from app.modules.eligibility.compatibility import matrix
from app.modules.eligibility.qualification import evaluated
from app.modules.optimizer.solver import solve
from app.modules.receipts.intake import read
from app.modules.reconcile.balance import balance
from app.modules.refunds.replay import replay
from app.modules.settlement.builder import build_settlement
from app.modules.trace.register import trace
from app.modules.versions.effective import classify
from app.modules.versions.registry import load


def process(source):
    receipts = read(source["events"])
    versions = classify(load(source["rules"]))
    digest = sha(canonical([source["events"], source["rules"]]))[:16]
    eligibility = {}
    optimizer = []
    for sale in receipts["sales"]:
        row = evaluated(sale, versions)
        row["matrix"] = matrix(row["qualified"], versions["pairs"])
        eligibility[sale["id"]] = row
        optimizer.append(solve(sale, row))
    refunds = replay(optimizer, receipts["returns"])
    checks = balance(receipts, optimizer, refunds)
    settlement = build_settlement(optimizer, refunds, checks, versions, digest)
    return {"receipts": receipts, "versions": versions, "eligibility": eligibility, "optimizer": optimizer,
            "refunds": refunds, "reconcile": checks,
            "settlement": settlement, "trace": trace(optimizer, eligibility, refunds, checks)}
