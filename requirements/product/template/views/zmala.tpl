% from markdown import markdown
% from build_tools.requirement_ids import groups
% themes = groups()
% titles = {'PROD': 'Product specification'}
% for component, entries in themes.items():
%   for group, label in entries.items():
%     for level in ('HLR', 'LLR'):
%       titles[f'{level}-{component}-{group}'] = ('Server' if component == 'SRV' else 'Pi terminal') + ' · ' + label + ' · ' + level
%     end
%   end
% end
% prefix = str(document.prefix) if is_doc else ''
% base = '../' if is_doc else ''
% title = titles[prefix] if is_doc else ('Traceability matrix' if doc_attributes['name'] == 'Traceability' else 'Requirements explorer')
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{title}} · ZmalaCall</title>
  <link rel="stylesheet" href="{{base}}template/zmala.css">
  <script src="{{base}}template/zmala.js" defer></script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="topbar">
  <a class="brand" href="{{base}}index.html"><span class="brand-mark">Z</span> ZmalaCall <span class="brand-label">Engineering</span></a>
  <nav aria-label="Report"><a href="{{base}}index.html">Overview</a><a href="{{base}}traceability.html">Traceability</a><a href="{{base}}coverage.html">Source coverage</a><a href="{{base}}tests.html">Tests</a></nav>
</header>
<div class="layout">
<aside class="sidebar">
  <p class="eyebrow">Specification → HLR → LLR</p>
  <nav aria-label="Requirement documents">
    <a class="doc-link" href="{{base}}documents/PROD.html">Product specification</a>
  % for component, entries in themes.items():
    <details class="theme-nav">
      <summary>{{'Server' if component == 'SRV' else 'Pi terminal'}}</summary>
    % for group, label in entries.items():
      <div class="theme-links"><span>{{label}}</span><div>
      % for level in ('HLR', 'LLR'):
        % key = f'{level}-{component}-{group}'
        <a class="{{'selected' if key == prefix else ''}}" href="{{base}}documents/{{key}}.html" {{!'aria-current="page"' if key == prefix else ''}}>{{level}}</a>
      % end
      </div></div>
    % end
    </details>
  % end
  </nav>
  % if is_doc:
  <details class="contents" open>
    <summary>On this page · {{len(document.items)}} items</summary>
    <nav aria-label="On this page">
    % for item in document.items:
      % if item.active:
      <a href="#{{item.uid}}"><span>{{item.uid}}</span>{{item.header}}</a>
      % end
    % end
    </nav>
  </details>
  % end
  <p class="sidebar-note">Implementation baseline<br>Linux server · Raspberry Pi terminal<br>Pi deployment installers included</p>
</aside>
<main id="main">
  <div class="page-heading"><p class="eyebrow">ZmalaCall requirements</p><h1>{{title}}</h1>
  % if is_doc:
    <p>{{len(document.items)}} requirements · {{'Product outcomes' if prefix == 'PROD' else 'Component behavior' if prefix.startswith('HLR-') else 'Implementation contracts and verification guidance'}}</p>
  % else:
    <p>From product intent to implementation, with navigable evidence and verification guidance.</p>
  % end
  </div>
  <p class="notice">This is an implementation-derived baseline. Source references and proposed checks are not test results or human approval. Optional and experimental behavior is marked explicitly.</p>
  % if is_doc:
  <div class="filter"><label for="search">Find on this page</label><input id="search" type="search" placeholder="ID, topic, source file or behavior…" autocomplete="off"><output id="match-count" aria-live="polite"></output></div>
  <div class="requirements">
  % for item in document.items:
    % if not item.active:
      % continue
    % end
    <article class="requirement" id="{{item.uid}}" data-search>
      <div class="item-meta"><a class="tag" href="#{{item.uid}}">{{item.uid}}</a><span>{{item.attribute('area')}}</span><span class="scope">{{item.attribute('scope')}}</span></div>
      <h2>{{item.header}}</h2>
      <div class="requirement-text">{{!markdown(str(item.text))}}</div>
      <div class="verification"><h3>How to verify</h3>{{!markdown(str(item.attribute('verification')))}}</div>
      % if item.parent_items:
      <div class="links"><strong>Derives from</strong>
      % for parent_item in item.parent_items:
        <a href="{{parent_item.document.prefix}}.html#{{parent_item.uid}}">{{parent_item.uid}} · {{parent_item.header}}</a>
      % end
      </div>
      % end
      % children = item.find_child_items()
      % if children:
      <details class="evidence"><summary>{{len(children)}} lower-level requirements</summary><ul>
      % for child in children:
        <li><a href="{{child.document.prefix}}.html#{{child.uid}}">{{child.uid}} · {{child.header}}</a></li>
      % end
      </ul></details>
      % end
      % if item.references:
      % if prefix.startswith('LLR-'):
      <p><a href="../coverage.html#trace-{{item.uid}}">Find code comment anchors →</a></p>
      % end
      <details class="evidence"><summary>Implementation and test references · {{len(item.references)}}</summary><ul>
      % for ref in item.references:
        <li><code>{{ref['path']}}</code></li>
      % end
      </ul></details>
      % end
      <p class="review-state">{{'Reviewed in Doorstop' if item.reviewed else 'Human review pending'}} · Verification execution is tracked separately</p>
    </article>
  % end
  </div>
  <p id="no-results" hidden>No requirements match this search.</p>
  % elif doc_attributes['name'] == 'Traceability':
  <p>Each row follows parent links. Empty cells in the other component branch are expected.</p>
  <div class="filter"><label for="search">Find a linked ID</label><input id="search" type="search" placeholder="For example, PROD008 or HLR-TERM-TV-002"><output id="match-count" aria-live="polite"></output><a href="traceability.csv" download>Download CSV</a></div>
  <div class="matrix" tabindex="0" aria-label="Scrollable traceability table">{{!body}}</div>
  % else:
  <div class="filter"><label for="search">Find a theme</label><input id="search" type="search" placeholder="Media, setup, remote…"><output id="match-count" aria-live="polite"></output></div>
  <section class="overview-grid" aria-label="Requirements hierarchy">
    <a class="overview-card product" href="documents/PROD.html"><span class="eyebrow">01 · Product intent</span><h2>Product specification</h2><p>User outcomes, operational boundaries and appliance responsibilities.</p><span class="card-action">Explore PROD →</span></a>
    % for component, entries in themes.items():
    <div class="branch"><h2>{{'Server' if component == 'SRV' else 'Pi terminal'}}</h2>
    % for group, label in entries.items():
      <section class="overview-card theme-card" data-search><span class="eyebrow">{{component}} · {{group}}</span><h3>{{label}}</h3>
        <div class="theme-levels"><a href="documents/HLR-{{component}}-{{group}}.html">High-level requirements →</a><a href="documents/LLR-{{component}}-{{group}}.html">Low-level requirements →</a></div>
      </section>
    % end
    </div>
    % end
  </section>
  <section class="reading-guide"><h2>Read and maintain this baseline</h2><p>Start with a product item and follow its lower-level links. Each LLR provides a specific behavior, a proposed check and implementation/test references. Use the source coverage index to find the requirements associated with a module.</p><p>The server and Pi terminal are in scope, including their installation tools. Windows terminal behavior, retired keypad/CAD work and third-party library internals are excluded. Referenced automated tests, manual scenarios and hardware checks require separate execution evidence.</p><p>Authoritative records are the YAML files in <code>requirements/</code>. This offline report is generated into <code>requirements/output/</code>; edit the records, then rebuild with <code>make requirements</code>.</p></section>
  % end
  <footer>Generated from Doorstop · <a href="#main">Back to top</a></footer>
</main>
</div>
</body>
</html>
