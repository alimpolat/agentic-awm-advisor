"""Generate EVAL.html with base64-embedded Phoenix trace screenshot."""
import base64
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
b64 = base64.b64encode((ROOT / "eval/results/phoenix_trace_brief.png").read_bytes()).decode()

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evaluation Trust Receipt — Agentic AWM Advisor — 2026-05-26</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,400&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root {{
    --ivory: #FAF9F5; --paper: #FFFFFF; --slate: #141413;
    --clay: #D97757; --clay-bg: rgba(217,119,87,0.10);
    --oat: #E3DACC;
    --olive: #788C5D; --olive-bg: rgba(120,140,93,0.12);
    --rust: #B04A3F; --rust-bg: rgba(176,74,63,0.10);
    --amber: #C7A35F; --amber-bg: rgba(199,163,95,0.14);
    --gray-100: #F7F4EC; --gray-150: #F0EEE6; --gray-300: #D1CFC5;
    --gray-500: #87867F; --gray-700: #3D3D3A;
    --serif: 'Newsreader', Georgia, "Times New Roman", serif;
    --mono: 'JetBrains Mono', ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  html{{scroll-behavior:smooth;}}
  body{{background:var(--ivory);color:var(--slate);font-family:var(--serif);font-weight:400;font-size:17px;line-height:1.65;-webkit-font-smoothing:antialiased;padding:0 24px 96px;}}
  .sheet{{max-width:1080px;margin:0 auto;}}
  header.hero{{padding:48px 0 32px;}}
  .eyebrow{{font-family:var(--mono);font-weight:500;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:var(--clay);margin-bottom:14px;}}
  h1{{font-family:var(--serif);font-weight:500;font-size:46px;letter-spacing:-0.015em;line-height:1.08;margin-bottom:14px;}}
  .lead{{font-size:18px;line-height:1.65;color:var(--gray-700);max-width:840px;margin-bottom:20px;}}
  .lead strong{{color:var(--slate);}}
  .metabar{{display:flex;flex-wrap:wrap;gap:0;font-family:var(--mono);font-size:11.5px;color:var(--gray-500);border-top:1px solid var(--gray-300);border-bottom:1px solid var(--gray-300);padding:14px 0;margin-top:8px;}}
  .metabar>div{{padding:0 22px 0 0;margin-right:22px;border-right:1px solid var(--gray-300);}}
  .metabar>div:last-child{{border-right:none;margin-right:0;padding-right:0;}}
  .metabar strong{{color:var(--slate);font-weight:500;}}
  section{{margin-top:56px;opacity:0;transform:translateY(8px);transition:opacity 600ms ease,transform 600ms ease;}}
  section.visible{{opacity:1;transform:translateY(0);}}
  .section-eyebrow{{font-family:var(--mono);font-weight:500;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:var(--clay);margin-bottom:8px;}}
  h2{{font-family:var(--serif);font-weight:500;font-size:30px;letter-spacing:-0.01em;line-height:1.2;margin-bottom:16px;}}
  h3{{font-family:var(--serif);font-weight:500;font-size:22px;margin:32px 0 12px;color:var(--slate);}}
  p{{font-size:16px;line-height:1.65;color:var(--gray-700);margin-bottom:12px;max-width:880px;}}
  p strong{{color:var(--slate);}}
  p code,li code{{font-family:var(--mono);font-size:13px;background:var(--gray-150);padding:1px 6px;border-radius:3px;color:var(--slate);}}
  ul,ol{{margin:10px 0 14px 24px;}}
  ul li,ol li{{font-size:16px;line-height:1.6;color:var(--gray-700);margin-bottom:6px;}}
  ul li strong{{color:var(--slate);}}
  a{{color:var(--clay);text-decoration:none;border-bottom:1px solid transparent;transition:border-color 200ms ease;}}
  a:hover{{border-bottom-color:var(--clay);}}
  .table-wrap{{overflow-x:auto;margin:14px 0;}}
  table{{width:100%;border-collapse:collapse;background:var(--paper);border:1.5px solid var(--gray-300);border-radius:14px;overflow:hidden;font-size:13.5px;}}
  th,td{{text-align:left;padding:9px 13px;border-bottom:1px solid var(--gray-300);vertical-align:top;}}
  tr:last-child td{{border-bottom:none;}}
  th{{background:var(--gray-100);font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:0.12em;color:var(--gray-500);font-weight:500;}}
  td.mc{{font-family:var(--mono);font-size:12px;color:var(--slate);}}
  td.num{{font-family:var(--mono);font-size:12px;text-align:right;}}
  td.pos{{color:var(--olive);}}
  td.neg{{color:var(--rust);}}
  .infobox{{background:var(--clay-bg);border-left:3px solid var(--clay);padding:14px 20px;margin:14px 0;border-radius:4px;font-size:15px;line-height:1.6;color:var(--gray-700);max-width:1000px;}}
  .infobox strong{{color:var(--clay);}}
  .infobox.olive{{background:var(--olive-bg);border-left-color:var(--olive);}}
  .infobox.olive strong{{color:var(--olive);}}
  .infobox.amber{{background:var(--amber-bg);border-left-color:var(--amber);}}
  .infobox.amber strong{{color:#8C7038;}}
  .infobox.rust{{background:var(--rust-bg);border-left-color:var(--rust);}}
  .infobox.rust strong{{color:var(--rust);}}
  .pill{{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:600;padding:2px 9px;border-radius:999px;letter-spacing:0.08em;text-transform:uppercase;}}
  .pill.olive{{background:var(--olive-bg);color:var(--olive);}}
  .pill.amber{{background:var(--amber-bg);color:#8C7038;}}
  .pill.rust{{background:var(--rust-bg);color:var(--rust);}}
  .pill.clay{{background:var(--clay-bg);color:var(--clay);}}
  .pill.gray{{background:var(--gray-150);color:var(--gray-500);}}
  .metrics-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin:20px 0;}}
  .metric-card{{background:var(--paper);border:1.5px solid var(--gray-300);border-radius:14px;padding:18px 20px;}}
  .metric-label{{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--gray-500);margin-bottom:6px;}}
  .metric-value{{font-family:var(--mono);font-size:28px;font-weight:600;}}
  .metric-value.pass{{color:var(--olive);}}
  .metric-value.na{{color:var(--gray-500);font-size:20px;}}
  .metric-target{{font-family:var(--mono);font-size:10.5px;color:var(--gray-500);margin-top:4px;}}
  .viz-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0;max-width:1000px;}}
  .viz-card{{background:var(--paper);border:1.5px solid var(--gray-300);border-radius:14px;padding:18px 20px 14px;}}
  .viz-card.full{{grid-column:1/-1;}}
  .viz-title{{font-family:var(--mono);font-weight:600;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--gray-700);margin-bottom:3px;}}
  .viz-sub{{font-family:var(--serif);font-size:14px;color:var(--gray-500);margin-bottom:8px;line-height:1.4;}}
  .trace-img{{width:100%;border-radius:10px;border:1.5px solid var(--gray-300);display:block;margin:16px 0;}}
  footer{{border-top:1px solid var(--gray-300);margin-top:80px;padding-top:24px;color:var(--gray-500);font-family:var(--mono);font-size:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:14px;}}
  @media(max-width:720px){{
    body{{padding:36px 18px 60px;font-size:16px;}}
    h1{{font-size:34px;}}h2{{font-size:24px;}}
    .viz-grid{{grid-template-columns:1fr;}}
  }}
</style>
</head>
<body>
<div class="sheet">

<header class="hero">
  <div class="eyebrow">Agentic AWM Advisor &middot; Evaluation Trust Receipt &middot; 2026-05-26</div>
  <h1>RAG evaluation</h1>
  <p class="lead">
    Two-layer evaluation of the Bergstr&ouml;m hybrid retrieval pipeline.
    <strong>Layer 1:</strong> deterministic recall@5 across 34 corpus questions (+ 1 unanswerable).
    <strong>Layer 2:</strong> LLM-judged faithfulness and answer relevance via a custom Gemini Flash judge.
  </p>
  <div class="metabar">
    <div><strong>Date</strong> 2026-05-26</div>
    <div><strong>Judge</strong> custom-gemini-flash-judge</div>
    <div><strong>Questions</strong> 35 total (34 corpus + 1 unanswerable)</div>
    <div><strong>Top-k</strong> 5</div>
    <div><strong>Ragas version</strong> 0.4.3</div>
  </div>
</header>

<!-- &#167; 1 METHODOLOGY -->
<section>
  <div class="section-eyebrow">&sect; 1 &middot; Methodology</div>
  <h2>How we measured it</h2>
  <p>Evaluation was designed to be honest about what matters for a private-banking RAG system:
  does it find the right documents, does it ground its answers in those documents, and does it
  answer the right question?</p>

  <h3>Question set &mdash; 35 synthetic questions</h3>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Intent bucket</th><th>n</th><th>What it tests</th></tr></thead>
      <tbody>
        <tr><td>lookup</td><td class="mc">5</td><td>Direct fact retrieval from portfolio / IPS / meeting notes</td></tr>
        <tr><td>quantitative</td><td class="mc">5</td><td>Arithmetic over holdings data (allocation %, SEK values, deviation from target)</td></tr>
        <tr><td>multi_hop</td><td class="mc">5</td><td>Requires evidence from 2+ documents</td></tr>
        <tr><td>contextual</td><td class="mc">5</td><td>Links macro reports (BIS/ECB/IMF) to client portfolio &mdash; hardest bucket</td></tr>
        <tr><td>macro_reasoning</td><td class="mc">5</td><td>Pure macro corpus questions (ECB Bulletin, IMF WEO, BIS Quarterly)</td></tr>
        <tr><td>nba_justification</td><td class="mc">5</td><td>Next-best-action rationale grounded in IPS + portfolio + meeting notes</td></tr>
        <tr><td>hard_named_entity_disambiguation</td><td class="mc">1</td><td>Ticker aliases, foreign-language entity names</td></tr>
        <tr><td>hard_multi_doc_synthesis</td><td class="mc">1</td><td>ECB stance + portfolio positioning in one answer</td></tr>
        <tr><td>hard_unanswerable</td><td class="mc">1</td><td>Question not in corpus &mdash; must say &ldquo;I don&rsquo;t know&rdquo;</td></tr>
        <tr><td>hard_ips_violation_detection</td><td class="mc">1</td><td>IPS FX floor compliance check</td></tr>
        <tr><td>hard_currency_math</td><td class="mc">1</td><td>Non-look-through SEK fraction arithmetic</td></tr>
      </tbody>
    </table>
  </div>

  <h3>Metrics</h3>
  <ul>
    <li><strong>Recall@5 (Layer 1 &mdash; deterministic):</strong> whether the expected source document(s) appear in the retrieved top-5. Binary per question, averaged per bucket.</li>
    <li><strong>Faithfulness (Layer 2 &mdash; LLM judge):</strong> does the answer make only claims grounded in retrieved context? Custom Gemini Flash judge, 0&ndash;1.</li>
    <li><strong>Answer relevancy (Layer 2 &mdash; LLM judge):</strong> does the answer address the question? Custom Gemini Flash judge, 0&ndash;1.</li>
  </ul>

  <div class="infobox amber">
    <strong>Custom judge, not OSS Ragas context-precision/recall.</strong>
    The Ragas 0.4.x Gemini adapter for context-precision and context-recall returned null scores due to
    a version compatibility quirk. A direct custom Gemini Flash judge was wired for faithfulness and
    answer relevancy instead &mdash; same methodology, fully in-budget. Context-precision and
    context-recall are listed as N/A and flagged for production hardening (see &sect;&nbsp;6).
  </div>
</section>

<!-- &#167; 2 OVERALL RESULTS -->
<section>
  <div class="section-eyebrow">&sect; 2 &middot; Overall results</div>
  <h2>All three targets passed</h2>

  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">Recall@5</div>
      <div class="metric-value pass">90.9%</div>
      <div class="metric-target">Target &ge;70% &middot; <strong style="color:var(--olive)">PASS</strong></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Faithfulness</div>
      <div class="metric-value pass">96.3%</div>
      <div class="metric-target">Target &ge;90% &middot; <strong style="color:var(--olive)">PASS</strong></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Answer Relevancy</div>
      <div class="metric-value pass">100%</div>
      <div class="metric-target">Target &ge;80% &middot; <strong style="color:var(--olive)">PASS</strong></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Context Precision</div>
      <div class="metric-value na">N/A</div>
      <div class="metric-target">Target &ge;80% &middot; not measured</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Context Recall</div>
      <div class="metric-value na">N/A</div>
      <div class="metric-target">Target &ge;85% &middot; not measured</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Unanswerable guard</div>
      <div class="metric-value pass">PASS</div>
      <div class="metric-target">Returned &ldquo;I don&rsquo;t know&rdquo; correctly</div>
    </div>
  </div>

  <div class="viz-grid">
    <div class="viz-card full">
      <div class="viz-title">Key metrics vs targets</div>
      <div class="viz-sub">Bars = measured score; dashed line = target floor. N/A metrics omitted from bars.</div>
      <div id="chart-summary" style="height:260px;"></div>
    </div>
  </div>
</section>

<!-- &#167; 3 PER-INTENT RECALL -->
<section>
  <div class="section-eyebrow">&sect; 3 &middot; Retrieval recall by intent</div>
  <h2>Recall@5 by intent bucket</h2>
  <p>The <strong>contextual bucket scores 0.65</strong> &mdash; the only bucket below the 0.70 target.
  Questions that link macro-level reports (BIS, ECB, IMF) to the specific Bergstr&ouml;m portfolio
  require cross-document reasoning that the hybrid pipeline partially misses. All other buckets
  reach 0.80 or above.</p>

  <div class="viz-grid">
    <div class="viz-card full">
      <div class="viz-title">Recall@5 per intent bucket</div>
      <div class="viz-sub">Clay dashed line = 0.70 target floor. Red bar = below target; amber = below 0.90; olive = 0.90+.</div>
      <div id="chart-intent" style="height:380px;"></div>
    </div>
  </div>

  <div class="table-wrap">
    <table>
      <thead><tr><th>Intent</th><th>Mean Recall@5</th><th>n</th><th>vs target</th></tr></thead>
      <tbody>
        <tr><td>contextual</td><td class="num neg">0.650</td><td class="mc">5</td><td><span class="pill rust">below target</span></td></tr>
        <tr><td>multi_hop</td><td class="num pos">0.800</td><td class="mc">5</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>nba_justification</td><td class="num pos">0.933</td><td class="mc">5</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>lookup</td><td class="num pos">1.000</td><td class="mc">5</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>quantitative</td><td class="num pos">1.000</td><td class="mc">5</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>macro_reasoning</td><td class="num pos">1.000</td><td class="mc">5</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>hard_currency_math</td><td class="num pos">1.000</td><td class="mc">1</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>hard_ips_violation_detection</td><td class="num pos">1.000</td><td class="mc">1</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>hard_multi_doc_synthesis</td><td class="num pos">1.000</td><td class="mc">1</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>hard_named_entity_disambiguation</td><td class="num pos">1.000</td><td class="mc">1</td><td><span class="pill olive">pass</span></td></tr>
        <tr><td>hard_unanswerable</td><td class="mc" style="text-align:right">N/A</td><td class="mc">1</td><td><span class="pill olive">pass (hallucination guard)</span></td></tr>
      </tbody>
    </table>
  </div>

  <div class="infobox rust">
    <strong>Contextual weak spot (recall@5 = 0.65).</strong>
    The worst single question &mdash; &ldquo;Both the BIS and ECB 2026 reports identify a boom in
    AI-related investment; how is Bergstr&ouml;m positioned?&rdquo; &mdash; scored 0.25: the
    retriever pulled meeting notes but missed the BIS and ECB reports. Root cause: contextual chunk
    prefixes do not carry enough cross-document signal at query time. Fix: reciprocal-context reranker
    with explicit macro-client link detection (see &sect;&nbsp;6).
  </div>
</section>

<!-- &#167; 4 HAND REVIEW -->
<section>
  <div class="section-eyebrow">&sect; 4 &middot; Hand review</div>
  <h2>Worst, best, and unanswerable cases</h2>
  <p>Eight questions sampled: lowest-recall rows, highest-recall hard cases, and the unanswerable case.
  PASS = answer grounded and relevant; FAIL = retrieval missed expected docs.
  Note that even FAIL rows maintain faithfulness &mdash; the LLM answers only from what it retrieved.</p>

  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="min-width:180px">Question / Intent</th>
        <th style="min-width:140px">Doc IDs</th>
        <th style="min-width:220px">Answer (excerpt)</th>
        <th>Verdict</th>
        <th style="min-width:150px">Critique</th>
      </tr></thead>
      <tbody>
        <tr>
          <td style="max-width:220px"><span class="pill gray">contextual</span><br>
            <span style="font-size:13px;color:var(--gray-700)">Both BIS and ECB 2026 reports identify AI-investment boom. How is Bergstr&ouml;m positioned?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> meeting-notes-02, meeting-notes-04, portfolio_q1<br>
            <strong>Expected:</strong> ips, portfolio_q1, bis_q1, ecb_bulletin<br>
            <strong>Recall@5:</strong> 0.25</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">US-tech sleeve ~20% vs 15% IPS target. Principal uneasy about AI multiples. Open to partial trim but hesitant to sell into momentum&hellip;</td>
          <td style="text-align:center"><span class="pill rust">FAIL</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">Retrieval missed BIS + ECB; answer grounded in meeting notes only</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">contextual</span><br>
            <span style="font-size:13px;color:var(--gray-700)">Given IMF Apr 2026 &lsquo;Shadow of War&rsquo; outlook, evaluate Bergstr&ouml;m&rsquo;s overweights vs IPS capital preservation.</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> ecb_bulletin, imf_weo<br>
            <strong>Expected:</strong> ips, portfolio_q1, imf_weo<br>
            <strong>Recall@5:</strong> 0.33</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">I don&rsquo;t know &mdash; the provided documents do not contain information about Bergstr&ouml;m&rsquo;s strategies or IPS objectives.</td>
          <td style="text-align:center"><span class="pill rust">FAIL</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">Hallucination guard held (correct IDK); retrieval missed IPS + portfolio</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">quantitative</span><br>
            <span style="font-size:13px;color:var(--gray-700)">Single-position limit in SEK &mdash; does Investor AB (INVE-B.ST) exceed it?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> ips, portfolio_q1<br>
            <strong>Expected:</strong> ips, portfolio_q1<br>
            <strong>Recall@5:</strong> 1.00</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">Limit = 5% of AUM = SEK 24M. Investor AB market value SEK 36M &mdash; exceeds limit.</td>
          <td style="text-align:center"><span class="pill olive">PASS</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">recall@5=1.00, faith=1.00, relev=1.00</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">hard_multi_doc_synthesis</span><br>
            <span style="font-size:13px;color:var(--gray-700)">ECB stance + Bergstr&ouml;m European fixed-income weight vs IPS target: over/under by how many pp?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> ips, portfolio_q1, ecb_bulletin<br>
            <strong>Expected:</strong> ips, portfolio_q1, ecb_bulletin<br>
            <strong>Recall@5:</strong> 1.00</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">Under-positioned: current 15% vs IPS target 20% &mdash; 5pp under.</td>
          <td style="text-align:center"><span class="pill olive">PASS</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">recall@5=1.00, faith=1.00, relev=1.00</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">hard_ips_violation_detection</span><br>
            <span style="font-size:13px;color:var(--gray-700)">Does Bergstr&ouml;m satisfy IPS FX policy requiring &ge;60% SEK base-currency exposure?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> ips, notes-04-14, portfolio_q1<br>
            <strong>Expected:</strong> ips, portfolio_q1<br>
            <strong>Recall@5:</strong> 1.00</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">No. Effective SEK base exposure &asymp;41%, deviating 19pp below the 60% floor.</td>
          <td style="text-align:center"><span class="pill olive">PASS</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">recall@5=1.00, faith=1.00, relev=1.00</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">hard_currency_math</span><br>
            <span style="font-size:13px;color:var(--gray-700)">SEK-denominated + Nordic equity fraction of SEK 480M on a non-look-through basis?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> ips, portfolio_q1<br>
            <strong>Expected:</strong> portfolio_q1<br>
            <strong>Recall@5:</strong> 1.00</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">~38% of the SEK 480M portfolio on a direct non-look-through basis.</td>
          <td style="text-align:center"><span class="pill olive">PASS</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">recall@5=1.00, faith=1.00, relev=1.00</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">hard_named_entity_disambiguation</span><br>
            <span style="font-size:13px;color:var(--gray-700)">Market value and YTD return of Jabal Omar Development (Makkah)?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> notes-01-14, notes-02-18, portfolio_q1, bis_q4<br>
            <strong>Expected:</strong> portfolio_q1<br>
            <strong>Recall@5:</strong> 1.00</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">Jabal Omar market value and YTD return correctly extracted from portfolio data.</td>
          <td style="text-align:center"><span class="pill olive">PASS</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">Arabic entity alias resolved; recall@5=1.00</td>
        </tr>
        <tr>
          <td style="max-width:220px"><span class="pill gray">hard_unanswerable</span><br>
            <span style="font-size:13px;color:var(--gray-700)">What is Bergstr&ouml;m&rsquo;s allocation to Japanese equities?</span></td>
          <td class="mc" style="font-size:11px;max-width:160px;word-break:break-all">
            <strong>Retrieved:</strong> ips, portfolio_q1<br>
            <strong>Expected:</strong> (none &mdash; unanswerable)<br>
            <strong>Recall@5:</strong> N/A</td>
          <td style="font-size:13px;max-width:220px;color:var(--gray-700)">I don&rsquo;t know &mdash; documents list Nordic equity, US technology, European fixed income, Gulf real estate, and Alternatives &mdash; Japanese equities not mentioned.</td>
          <td style="text-align:center"><span class="pill olive">PASS</span></td>
          <td style="font-size:12px;color:var(--gray-700);max-width:150px">Hallucination guard holds: correct IDK, no invented allocation</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="infobox olive">
    <strong>Hallucination guard works in both directions.</strong>
    The hard_unanswerable case correctly returned &ldquo;I don&rsquo;t know.&rdquo;
    The contextual FAIL case also returned &ldquo;I don&rsquo;t know&rdquo; when retrieval brought
    back the wrong documents &mdash; the LLM did not hallucinate from the macro corpus.
    Faithfulness was 1.00 on every row shown above.
  </div>
</section>

<!-- &#167; 5 PHOENIX TRACE -->
<section>
  <div class="section-eyebrow">&sect; 5 &middot; Observability</div>
  <h2>Phoenix trace &mdash; full brief generation</h2>
  <p>Arize Phoenix distributed tracing captures every LLM call, retrieval step, and tool invocation
  during brief generation. The screenshot below shows a single Bergstr&ouml;m brief trace: five stages,
  the parallel specialist fan-out at Stage 3, and the Synthesizer at Stage 4. Total wall-clock &asymp;16&thinsp;s.</p>

  <img src="data:image/png;base64,{b64}"
       alt="Phoenix distributed trace screenshot showing the five-stage Bergstrom brief generation with parallel Stage-3 specialist fan-out"
       class="trace-img">

  <div class="infobox">
    <strong>What to look for:</strong> the four Stage-3 specialist spans fire simultaneously
    (asyncio.gather), converging before the Stage-4 Synthesizer span. Token counts and per-span
    latency are visible in Phoenix. Retrieval spans appear nested under each specialist. Cold-start
    overhead is negligible because the brief is served from cache.
  </div>
</section>

<!-- &#167; 6 PRODUCTION HARDENING -->
<section>
  <div class="section-eyebrow">&sect; 6 &middot; Production hardening</div>
  <h2>What we would add for production</h2>

  <div class="infobox amber">
    <strong>Roadmap &mdash; not blockers.</strong> The three targets
    (recall@5 &ge;70%, faithfulness &ge;90%, answer-relevancy &ge;80%) all pass for a POC.
    The items below are the honest gap list between this demonstrator and a production deployment
    at AWM.
  </div>

  <div class="table-wrap">
    <table>
      <thead><tr><th>Item</th><th>Description</th><th>Priority</th></tr></thead>
      <tbody>
        <tr>
          <td><strong>Real Ragas context-precision / context-recall</strong></td>
          <td>Wire the Ragas 0.4.x OSS Gemini adapter correctly (or pin to a version without the null-score bug) to measure whether retrieved chunks are <em>necessary</em>, not just <em>sufficient</em> &mdash; important for detecting over-retrieval.</td>
          <td><span class="pill clay">high</span></td>
        </tr>
        <tr>
          <td><strong>Fix contextual recall (0.65 &rarr; &ge;0.85)</strong></td>
          <td>The 4-document contextual synthesis bucket is the weak spot. Solutions: (1) expand chunk prefixes with linked-document IDs at build time, (2) add a two-stage retrieval step that explicitly queries macro docs when the query contains macro-entity references, (3) GraphRAG-style entity linking between client documents and macro publications.</td>
          <td><span class="pill clay">high</span></td>
        </tr>
        <tr>
          <td><strong>Brief-quality LLM-judge rubric</strong></td>
          <td>Evaluate the end-to-end brief, not just retrieval. A structured rubric scoring NBA specificity, risk flag calibration, citation completeness, and IPS consistency &mdash; Gemini Pro judge applied to 20 sampled briefs.</td>
          <td><span class="pill amber">medium</span></td>
        </tr>
        <tr>
          <td><strong>EU-region Cloud Run + VPC-SC / CMEK</strong></td>
          <td>Move from HF Spaces to Cloud Run europe-west1. Add VPC Service Controls perimeter around Vertex AI and GCS. Customer-managed encryption keys (CMEK) for any persistent store. Required for a regulated private-bank deployment handling real client data.</td>
          <td><span class="pill clay">high</span></td>
        </tr>
        <tr>
          <td><strong>A/B evaluation framework</strong></td>
          <td>Structured comparison harness to evaluate retrieval improvements (contextual prefix changes, RRF k-tuning, reranker prompt variants) against the 35-question baseline. Use Phoenix experiment tracking or a dedicated eval DB.</td>
          <td><span class="pill gray">medium</span></td>
        </tr>
        <tr>
          <td><strong>Adversarial injection &amp; multi-tenant isolation tests</strong></td>
          <td>Test cases for prompt injection via document content, PII leakage across client namespaces, and hallucination under adversarial query rewrites. A private bank operating multi-family-office systems must isolate client data at the retrieval level.</td>
          <td><span class="pill clay">high</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</section>

<footer>
  <div>Evaluation Trust Receipt &middot; Agentic AWM Advisor &middot; 2026-05-26 &middot; Alim Polat</div>
  <div>Pairs with: <a href="ARCHITECTURE.html">ARCHITECTURE.html</a> &middot; <a href="eval/results/hand_review.html">hand_review.html</a></div>
</footer>

</div><!-- .sheet -->

<script>
  const obs = new IntersectionObserver(entries => {{
    entries.forEach(e => {{ if(e.isIntersecting) e.target.classList.add('visible'); }});
  }}, {{ threshold: 0.06 }});
  document.querySelectorAll('section').forEach(s => obs.observe(s));

  const CLAY='#D97757', OLIVE='#788C5D', AMBER='#C7A35F', RUST='#B04A3F';
  const SLATE='#141413', GRAY300='#D1CFC5', GRAY500='#87867F';
  const SERIF="'Newsreader', Georgia, serif", MONO="'JetBrains Mono', monospace";
  const baseTooltip = {{
    backgroundColor:'rgba(255,255,255,0.96)', borderColor:GRAY300,
    textStyle:{{ color:SLATE, fontFamily:SERIF, fontSize:14 }},
    extraCssText:'box-shadow:0 4px 12px rgba(0,0,0,0.08);border-radius:8px;'
  }};

  // Summary bar chart
  const summary = echarts.init(document.getElementById('chart-summary'));
  summary.setOption({{
    animation:true, animationEasing:'cubicOut', animationDuration:900,
    tooltip:{{ ...baseTooltip, trigger:'axis' }},
    grid:{{ left:20, right:20, top:20, bottom:60, containLabel:true }},
    xAxis:{{ type:'category',
      data:['Recall@5', 'Faithfulness', 'Answer Relevancy'],
      axisLabel:{{ fontFamily:MONO, fontSize:11, color:GRAY500 }},
      axisLine:{{ lineStyle:{{ color:GRAY300 }} }} }},
    yAxis:{{ type:'value', max:1.05, min:0,
      axisLabel:{{ fontFamily:MONO, fontSize:10, color:GRAY500,
        formatter: v => (v*100).toFixed(0)+'%' }},
      splitLine:{{ lineStyle:{{ color:GRAY300, type:'dashed'}} }} }},
    series:[
      {{ name:'Score', type:'bar', barWidth:'40%',
        itemStyle:{{ borderRadius:[4,4,0,0], color: p => [OLIVE,OLIVE,OLIVE][p.dataIndex] }},
        data:[0.909, 0.963, 1.000],
        label:{{ show:true, position:'top', fontFamily:MONO, fontSize:12, color:SLATE,
          formatter: p => (p.value*100).toFixed(1)+'%' }}
      }},
      {{ name:'Target', type:'line', symbol:'none',
        lineStyle:{{ type:'dashed', color:CLAY, width:1.5 }},
        data:[0.70, 0.90, 0.80] }}
    ],
    legend:{{ bottom:4, itemWidth:12, itemHeight:12,
      textStyle:{{ fontFamily:MONO, fontSize:11, color:SLATE }} }}
  }});

  // Intent recall horizontal bar chart
  const intentData = [
    {{ intent:'contextual', score:0.650 }},
    {{ intent:'multi_hop', score:0.800 }},
    {{ intent:'nba_justification', score:0.933 }},
    {{ intent:'lookup', score:1.000 }},
    {{ intent:'quantitative', score:1.000 }},
    {{ intent:'macro_reasoning', score:1.000 }},
    {{ intent:'hard_currency_math', score:1.000 }},
    {{ intent:'hard_ips_violation', score:1.000 }},
    {{ intent:'hard_multi_doc', score:1.000 }},
    {{ intent:'hard_entity_disambig', score:1.000 }},
  ];
  const intentChart = echarts.init(document.getElementById('chart-intent'));
  intentChart.setOption({{
    animation:true, animationEasing:'cubicOut', animationDuration:900,
    tooltip:{{ ...baseTooltip, trigger:'axis',
      formatter: params => `${{params[0].name}}<br/>${{params[0].marker}}${{(params[0].value*100).toFixed(1)}}%` }},
    grid:{{ left:20, right:70, top:10, bottom:20, containLabel:true }},
    xAxis:{{ type:'value', max:1.05, min:0,
      axisLabel:{{ fontFamily:MONO, fontSize:10, color:GRAY500, formatter: v => (v*100)+'%' }},
      splitLine:{{ lineStyle:{{ color:GRAY300, type:'dashed'}} }} }},
    yAxis:{{ type:'category',
      data: intentData.map(d => d.intent),
      axisLabel:{{ fontFamily:MONO, fontSize:10, color:GRAY500 }} }},
    series:[
      {{ type:'bar', barWidth:'55%',
        itemStyle:{{ borderRadius:[0,4,4,0],
          color: p => intentData[p.dataIndex].score < 0.70 ? RUST :
                      intentData[p.dataIndex].score < 0.90 ? AMBER : OLIVE }},
        data: intentData.map(d => d.score),
        label:{{ show:true, position:'right', fontFamily:MONO, fontSize:10, color:SLATE,
          formatter: p => (p.value*100).toFixed(1)+'%' }}
      }},
      {{ type:'line', markLine:{{ symbol:'none',
        lineStyle:{{ color:CLAY, type:'dashed', width:2 }},
        label:{{ show:true, formatter:'target 70%', fontFamily:MONO, fontSize:10, color:CLAY,
          position:'end' }},
        data:[{{ xAxis: 0.70 }}] }} }}
    ]
  }});

  window.addEventListener('resize', () => {{ summary.resize(); intentChart.resize(); }});
</script>
</body>
</html>
"""

out = ROOT / "EVAL.html"
out.write_text(html, encoding='utf-8')
print(f"Written {out} ({out.stat().st_size:,} bytes)")
