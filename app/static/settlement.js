import {cash, grid, head, pill, reason, text} from './format.js';

function originalPanel(sheet) {
  if (!sheet.original) {
    return head('原组合（无有效原票）') + pill(reason(sheet.reason), 'bad') +
      grid(['阻断退单','明细','件数','实退','原因'], sheet.blocked_returns.map(r =>
        [r.id, r.line, r.qty, cash(r.cash), reason(r.reason)]), [2, 3]);
  }
  const o = sheet.original;
  return head('原组合 · 原票口径', pill(o.chosen.join(' + ') || '未用券', 'good')) +
    grid(['券 · 版本','明细分摊','减免'], o.applied.map(a =>
      [`${a.code} · ${a.version}`, Object.entries(a.shares).map(([k, v]) => `${k} ${cash(v)}`).join(' / '), cash(a.amount)]), [2]) +
    `<div class="explain"><span>商品毛额 ${cash(o.gross)} · 实摊优惠 ${cash(o.discount)}</span><strong>${cash(o.due)}</strong></div>`;
}

function remainingPanel(sheet) {
  const r = sheet.remaining;
  if (r.basket_empty) {
    return head('剩余可用组合') + pill('商品已全部退回', '');
  }
  return head('剩余可用组合（按原票时点规则重判）') +
    grid(['原券','剩余资格','合格基数'], r.findings.map(f =>
      [f.coupon, reason(f.reason), cash(f.eligible_gross)], [2])) +
    grid(['可发布组合','复算实付'], r.trials.slice(0, 5).map(t =>
      [t.codes.join(' + ') || '原价（无可用券）', cash(t.due)]), [1]);
}

function linesPanel(sheet) {
  if (!sheet.lines.length) return head('已退 / 未退') + '<p>暂无明细口径</p>';
  return head('已退 / 未退（沿原票按件冲减）') +
    grid(['明细','品类','原件/已退/剩余','已退款','剩余净额','结构差'], sheet.lines.map(l =>
      [l.line, l.category, `${l.qty} / ${l.returned_qty} / ${l.retained_qty}`,
       cash(l.refunded), cash(l.retained_net), l.gap ? cash(l.gap) : '对平']), [5]);
}

function returnsPanel(sheet) {
  const posted = grid(['退单','明细','件数','商品额','冲减优惠','应退','实退','现金差'], sheet.returns.map(r =>
    [r.id, r.line, r.qty, cash(r.gross), cash(r.discount), cash(r.expected), cash(r.cash),
     r.cash_gap ? cash(r.cash_gap) : '一致']), [2, 3, 4, 5, 6, 7]);
  const blocked = sheet.blocked_returns.length
    ? '<h3>阻断退单（留痕不冲减）</h3>' + grid(['退单','明细','件数','实退','原因'],
        sheet.blocked_returns.map(r => [r.id, r.line, r.qty, cash(r.cash), reason(r.reason)]), [2, 3])
    : '';
  return head('退货流水与冲减') + posted + blocked;
}

function differencePanel(sheet) {
  const rows = sheet.differences.map(d => d.reason === 'COUPON_THRESHOLD_DRIFT'
    ? [d.coupon, reason(d.reason), `剩余合格基数 ${cash(d.eligible_gross)}`, '仅解释，不改账']
    : [d.id, reason(d.reason), cash(d.gap), `应退 ${cash(d.expected)} / 实退 ${cash(d.cash)}`]);
  const blocking = sheet.blocking.length
    ? '<h3>发布阻断</h3>' + grid(['原因','涉及'], sheet.blocking.map(b =>
        [reason(b.reason), text(b.claims ? b.claims.join('、') : (b.lines ? b.lines.map(x => x.line).join('、') : b.gap))]))
    : '';
  return head('差异来源与发布闸门', sheet.publishable ? pill('可发布', 'good') : pill('禁止发布', 'bad')) +
    (rows.length ? grid(['业务键/券','来源','金额/基数','处置'], rows) : '<p>无差异，结构对平</p>') + blocking;
}

export function settlementView(result, sheet, picker) {
  if (!sheet) return [head('退货结算复核单', picker) + '<p>该批次没有退货复核单</p>', head('发布状态') + '<p>—</p>'];
  const t = sheet.totals;
  const summary = sheet.original
    ? `<div class="tags">${pill(`复核单 ${text(sheet.id)}`)}${pill(sheet.publishable ? '可发布' : '禁止发布', sheet.publishable ? 'good' : 'bad')}</div>
       <div class="explain"><span>应退 ${cash(t.refunded)} · 实退 ${cash(t.cash_refunded)} · 剩余净额 ${cash(t.retained_net)}</span><strong>${cash(t.due)}</strong></div>`
    : `<div class="tags">${pill(`复核单 ${text(sheet.id)}`)}${pill('禁止发布', 'bad')}</div>`;
  const left = head('退货结算复核单', picker) + summary + originalPanel(sheet) + remainingPanel(sheet);
  const right = linesPanel(sheet) + returnsPanel(sheet) + differencePanel(sheet);
  return [left, right];
}
