"use strict";
const API = '';
const WS = new URLSearchParams(location.search).get('workspace') || 'global';

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) Object.entries(attrs).forEach(function(entry) {
    var k = entry[0], v = entry[1];
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  });
  children.forEach(function(c) {
    if (typeof c === 'string') e.appendChild(document.createTextNode(c));
    else if (c) e.appendChild(c);
  });
  return e;
}

async function loadStats() {
  var r = await fetch(API + '/api/stats?workspace=' + encodeURIComponent(WS));
  var d = await r.json();
  document.getElementById('workspace-info').textContent = 'workspace: ' + d.workspace;
  var container = document.getElementById('stats');
  container.textContent = '';
  [[d.documents, 'Documents'], [d.wiki_pages, 'Wiki Pages'],
   [d.beliefs, 'Beliefs'], [d.topics.length, 'Topics'], [d.runs, 'Runs']
  ].forEach(function(pair) {
    container.appendChild(el('div', {class: 'stat-card'},
      el('div', {class: 'value'}, String(pair[0])),
      el('div', {class: 'label'}, pair[1])
    ));
  });
}

async function doSearch() {
  var q = document.getElementById('search-input').value.trim();
  if (!q) return;
  var r = await fetch(API + '/api/search?q=' + encodeURIComponent(q) + '&workspace=' + encodeURIComponent(WS));
  var d = await r.json();
  var panel = document.getElementById('search-results');
  var body = document.getElementById('results-body');
  panel.style.display = 'block';
  body.textContent = '';

  if (!d.results.length) {
    body.appendChild(el('div', {class: 'empty'}, 'No results'));
    return;
  }

  var table = el('table');
  table.appendChild(el('thead', null, el('tr', null,
    el('th', null, 'Title'), el('th', null, 'Score'),
    el('th', null, 'Beliefs'), el('th', null, 'Layer')
  )));
  var tbody = el('tbody');
  d.results.forEach(function(result) {
    var row = el('tr', {class: 'clickable', onclick: function() { readDoc(result.path); }},
      el('td', null, result.title),
      el('td', {class: 'score'}, String(result.score)),
      el('td', null, String(result.belief_count || '-')),
      el('td', null, result.layer)
    );
    tbody.appendChild(row);
  });
  table.appendChild(tbody);
  body.appendChild(table);
}

async function readDoc(path) {
  var r = await fetch(API + '/api/documents?path=' + encodeURIComponent(path) + '&workspace=' + encodeURIComponent(WS));
  var d = await r.json();
  var viewer = document.getElementById('doc-viewer');
  viewer.classList.add('active');
  document.getElementById('doc-title').textContent = d.title || d.path;
  document.getElementById('doc-content').textContent = d.content;
}

async function loadBeliefs() {
  var r = await fetch(API + '/api/beliefs?workspace=' + encodeURIComponent(WS) + '&limit=100');
  var d = await r.json();
  var body = document.getElementById('beliefs-body');
  document.getElementById('belief-count').textContent = '(' + d.beliefs.length + ')';
  body.textContent = '';

  if (!d.beliefs.length) {
    body.appendChild(el('div', {class: 'empty'}, 'No beliefs'));
    return;
  }

  var table = el('table');
  table.appendChild(el('thead', null, el('tr', null,
    el('th', null, 'Statement'), el('th', null, 'Topic'), el('th', null, 'Subject')
  )));
  var tbody = el('tbody');
  d.beliefs.forEach(function(b) {
    tbody.appendChild(el('tr', null,
      el('td', null, b.statement),
      el('td', null, el('span', {class: 'topic-tag'}, b.topic)),
      el('td', null, b.subject || '')
    ));
  });
  table.appendChild(tbody);
  body.appendChild(table);
}

document.getElementById('search-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') doSearch();
});
document.getElementById('search-btn').addEventListener('click', doSearch);

loadStats();
loadBeliefs();
