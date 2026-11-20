import sqlite3

from app.config import db_path


def sheet(dirty, order):
    return next(x for x in dirty['settlement']['sheets'] if x['order'] == order)


def test_deterministic_sheet_id(dirty, clean):
    a = sheet(dirty, '000760')['id']
    b = sheet(dirty, '000760')['id']
    assert a == b and len(a) == 16
    assert a != sheet(clean, '000731')['id']


def test_multi_part_refund_keeps_original_basis(dirty):
    """同一张券分两次退：已退沿用原票按件冲减，结构恒等对平。"""
    sh = sheet(dirty, '000760')
    assert [(r['id'], r['qty'], r['gross'], r['discount'], r['expected']) for r in sh['returns']] == [
        ('R020', 1, 1000, 150, 850), ('R021', 2, 2000, 300, 1700)]
    assert sh['totals']['refunded'] == 2550
    assert all(line['gap'] == 0 for line in sh['lines'])
    assert sh['totals']['due'] == sh['totals']['refunded'] + sh['totals']['retained_net']


def test_remaining_combo_threshold_drift(dirty):
    """剩余商品已达不到原券门槛：只解释差异来源，不回头重算已退款。"""
    sh = sheet(dirty, '000760')
    remaining = sh['remaining']
    assert remaining['basket_empty'] is False
    assert remaining['findings'][0]['reason'] == 'MINIMUM_NOT_MET'
    assert remaining['findings'][0]['eligible_gross'] == 1000
    assert remaining['trials'] == [{'codes': [], 'due': 1000}]
    drift = next(x for x in sh['differences'] if x['reason'] == 'COUPON_THRESHOLD_DRIFT')
    assert drift['coupon'] == '满30减6'
    # 剩余件仍承接原票分摊口径，未做二次减免或冲回
    assert sh['totals']['retained_discount'] == 150
    assert sh['publishable'] is True


def test_cash_gap_listed_but_still_publishable(dirty):
    """实退与应退的现金差额只列示，不构成发布阻断（账仍按原票口径对平）。"""
    sh = sheet(dirty, '000734')
    gap = next(x for x in sh['differences'] if x['reason'] == 'RETURN_CASH_GAP')
    assert (gap['expected'], gap['cash'], gap['gap']) == (600, 599, -1)
    assert sh['publishable'] is True and sh['blocking'] == []


def test_missing_or_isolated_sale_blocks(dirty):
    """原单隔离：不形成可发布复核单，退货全部留痕且阻断。"""
    sh = sheet(dirty, '000750')
    assert sh['publishable'] is False and sh['original'] is None
    assert [b['reason'] for b in sh['blocking']] == ['SALE_ISOLATED']
    assert [r['id'] for r in sh['blocked_returns']] == ['R010']
    # 缺原票的退货不并入任何单，作为孤儿退货单独留痕
    assert [o['id'] for o in dirty['settlement']['orphan_returns']] == ['R014']


def test_blocked_return_claims_hold_publish(dirty):
    """超件、缺行、早于原购的退货被阻断时，复核单不可发布但记录不丢。"""
    sh = sheet(dirty, '000731')
    assert sh['publishable'] is False
    block = next(b for b in sh['blocking'] if b['reason'] == 'RETURN_CLAIM_BLOCKED')
    assert block['claims'] == ['R013', 'R012', 'R011']
    assert {r['id'] for r in sh['returns']} == {'R001', 'R002'}
    assert {r['id'] for r in sh['blocked_returns']} == {'R011', 'R012', 'R013'}


def test_fully_returned_basket_is_empty(dirty):
    sh = sheet(dirty, '000731')
    assert sh['remaining']['basket_empty'] is True
    assert sh['totals']['retained_net'] == 0


def test_clean_batch_all_publishable(clean):
    assert clean['settlement']['orphan_returns'] == []
    assert all(x['publishable'] for x in clean['settlement']['sheets'])


def test_retransmitted_return_not_double_deducted(dirty):
    """同键重传在采信阶段只保留一条，复核单冲减件数与金额不翻倍。"""
    intake = dirty['receipts']
    replay_rows = [r for r in intake['rows'] if r['code'] == 'DUPLICATE_REPLAY']
    assert replay_rows and all(r['id'] == '000731' for r in replay_rows)
    sh = sheet(dirty, '000731')
    # 原票 3 件，已退恰好 3 件（R001 一件 + R002 两件），重传行未再次冲减
    assert sum(r['qty'] for r in sh['returns']) == 3
    assert sh['totals']['refunded'] == sh['totals']['due'] == 4900


def test_publish_endpoint_gate_and_retry(client):
    run = client.post('/api/runs', json={'sample': 'dirty'}).json()
    good = sheet(run['result'], '000760')
    bad = sheet(run['result'], '000750')

    first = client.post(f"/api/runs/{run['id']}/settlements/{good['id']}/publish").json()
    assert first['published'] is True and first['reused'] is False
    # 相同退货重试：同一复核单只入账一次，不重复冲减
    again = client.post(f"/api/runs/{run['id']}/settlements/{good['id']}/publish").json()
    assert again['reused'] is True and again['id'] == first['id']
    listed = client.get(f"/api/runs/{run['id']}/settlements").json()['settlements']
    assert [x['id'] for x in listed] == [good['id']]

    refused = client.post(f"/api/runs/{run['id']}/settlements/{bad['id']}/publish")
    assert refused.status_code == 422 and refused.json()['code'] == 'SETTLEMENT_NOT_PUBLISHABLE'
    with sqlite3.connect(db_path()) as conn:
        assert conn.execute('SELECT COUNT(*) FROM settlements').fetchone()[0] == 1

    fetched = client.get(f"/api/runs/{run['id']}/settlements/{good['id']}").json()
    assert fetched['id'] == good['id']
    missing = client.get(f"/api/runs/{run['id']}/settlements/{bad['id']}")
    assert missing.status_code == 404 and missing.json()['code'] == 'SETTLEMENT_NOT_FOUND'


def test_publish_unknown_run_404(client):
    r = client.post('/api/runs/nope/settlements/abc/publish')
    assert r.status_code == 404 and r.json()['code'] == 'RUN_NOT_FOUND'


def test_sample_settlement_endpoint(client, dirty):
    data = client.get('/api/samples/dirty/settlement').json()
    assert data['digest'] == dirty['settlement']['digest']
    one = client.get('/api/samples/dirty/settlement', params={'order': '000760'}).json()
    assert one['id'] == sheet(dirty, '000760')['id']
    assert client.get('/api/samples/dirty/settlement', params={'order': 'nope'}).status_code == 404


def test_parallel_publish_inserts_once(client):
    """中断恢复或并发重试：同一张复核单只入账一次，冲减不重复。"""
    from concurrent.futures import ThreadPoolExecutor
    run = client.post('/api/runs', json={'sample': 'clean'}).json()
    target = run['result']['settlement']['sheets'][0]
    with ThreadPoolExecutor(4) as pool:
        records = list(pool.map(
            lambda _: client.post(f"/api/runs/{run['id']}/settlements/{target['id']}/publish").json(),
            range(4)))
    assert {r['id'] for r in records} == {target['id']}
    assert [r['reused'] for r in records].count(False) == 1
    with sqlite3.connect(db_path()) as conn:
        assert conn.execute('SELECT COUNT(*) FROM settlements').fetchone()[0] == 1
