// Local-only enhancement: all requirements and trace links work without JavaScript.
(() => {
  const search = document.querySelector('#search');
  if (!search) return;
  const cards = [...document.querySelectorAll('[data-search]')];
  const rows = cards.length ? cards : [...document.querySelectorAll('.matrix tbody tr')];
  const index = rows.map((row) => ({ row, text: row.textContent.toLocaleLowerCase() }));
  const count = document.querySelector('#match-count');
  const empty = document.querySelector('#no-results');
  const filter = () => {
    const terms = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const { row, text } of index) {
      row.hidden = !terms.every((term) => text.includes(term));
      if (!row.hidden) shown++;
    }
    if (count) count.textContent = `${shown} of ${rows.length} shown`;
    if (empty) empty.hidden = shown > 0;
  };
  const revealAnchor = () => {
    const target = document.getElementById(location.hash.slice(1));
    if (target && target.hidden) {
      search.value = '';
      filter();
      target.scrollIntoView();
    }
  };
  search.addEventListener('input', filter);
  addEventListener('hashchange', revealAnchor);
  filter();
})();
