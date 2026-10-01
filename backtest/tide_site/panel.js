// 潮汐策略首頁區塊：讀 tide/status.json，畫在 index.html 的 <div id="tide-panel"> 裡。
// 由潮汐工作流程部署到 gh-pages 的 tide/；選股流程重建 index.html 只需保留那個 div 與這支 script。
(function () {
  const root = document.getElementById('tide-panel');
  if (!root) return;

  const css = `
    #tide-panel { margin-bottom: 28px; }
    .tide-card { border: 1px solid #dfe3f5; border-left: 5px solid #667eea; border-radius: 14px;
      background: #f7f8ff; padding: 20px 22px; color: #1f2544; }
    .tide-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 16px; }
    .tide-head h2 { font-size: 1.25em; margin: 0; color: #3b3f8f; }
    .tide-close { font-size: 1.05em; font-weight: 600; }
    .tide-up { color: #d64550; } .tide-down { color: #1e9e5a; }
    .tide-row { margin-top: 10px; line-height: 1.6; white-space: pre-line; }
    .tide-row b { color: #3b3f8f; }
    .tide-table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.95em; }
    .tide-table td { padding: 7px 10px; border-top: 1px solid #e3e6f5; vertical-align: top; }
    .tide-table td:first-child { white-space: nowrap; font-variant-numeric: tabular-nums; color: #3b3f8f; font-weight: 600; }
    .tide-notes { margin-top: 10px; font-size: 0.82em; color: #6b7090; line-height: 1.6; }
    .tide-link { display: inline-block; margin-top: 12px; padding: 7px 14px; border-radius: 8px;
      background: #667eea; color: #fff; text-decoration: none; font-size: 0.92em; }
    .tide-link:hover { background: #5a6fd8; }
    @media (max-width: 560px) { .tide-table td:first-child { white-space: normal; } }
  `;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  fetch('tide/status.json?ts=' + Date.now())
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(s => {
      const style = document.createElement('style');
      style.textContent = css;
      document.head.appendChild(style);

      const card = el('div', 'tide-card');
      const head = el('div', 'tide-head');
      head.appendChild(el('h2', null, '🌊 潮汐策略｜' + s.date.replace(/-/g, '/') + ' 收盤'));
      const closeEl = el('span', 'tide-close', '加權指數 ' + s.close.toLocaleString('en-US', { minimumFractionDigits: 2 }) + ' ');
      const chg = el('span', s.change_pct >= 0 ? 'tide-up' : 'tide-down',
        '(' + (s.change_pct >= 0 ? '+' : '') + s.change_pct.toFixed(2) + '%)');
      closeEl.appendChild(chg);
      head.appendChild(closeEl);
      card.appendChild(head);

      [['今日收盤動作', s.today_action], ['部位', s.position]].forEach(([k, v]) => {
        const row = el('div', 'tide-row');
        row.appendChild(el('b', null, k + '：'));
        row.appendChild(document.createTextNode(v));
        card.appendChild(row);
      });

      const nd = s.next_date.slice(5).replace('-', '/');
      const title = el('div', 'tide-row');
      title.appendChild(el('b', null, '📋 下一個交易日（' + nd + '，遇假日順延）收盤情境'));
      card.appendChild(title);
      const table = el('table', 'tide-table');
      s.scenarios.forEach(r => {
        const tr = document.createElement('tr');
        tr.appendChild(el('td', null, r.range));
        tr.appendChild(el('td', null, r.action));
        table.appendChild(tr);
      });
      card.appendChild(table);

      const notes = el('div', 'tide-notes');
      s.notes.forEach(n => notes.appendChild(el('div', null, '※ ' + n)));
      notes.appendChild(el('div', null, '更新時間：' + s.generated_at.replace('T', ' ')));
      card.appendChild(notes);

      const link = el('a', 'tide-link', '看進出場圖表 →');
      link.href = 'tide/';
      card.appendChild(link);
      root.appendChild(card);
    })
    .catch(() => { root.hidden = true; });  // 還沒有潮汐資料就不顯示
})();
