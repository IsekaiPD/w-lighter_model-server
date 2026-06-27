import html
import json
import math
from datetime import datetime


GRAPH_WIDTH = 1180
GRAPH_HEIGHT = 860
NORMAL_NODE_SIZE = (184, 84)
MAIN_NODE_SIZE = (222, 100)

STYLE_COLORS = {
    "romance": "#D85C8A",
    "partnership": "#5BAE5B",
    "hierarchy": "#6A4FB3",
    "rivalry": "#D6453D",
    "mentorship": "#3A8FD8",
    "family": "#D98A2B",
    "organization": "#4B6FAE",
    "neutral": "#8A8A8A",
}

STYLE_LABELS = {
    "romance": "연애/개인",
    "partnership": "협력/신뢰",
    "hierarchy": "권력/상하",
    "rivalry": "대립/갈등",
    "mentorship": "조언/스승",
    "family": "가족/혈연",
    "organization": "조직/소속",
    "neutral": "기타",
}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def node_size_for(item: dict | None) -> tuple[int, int]:
    return MAIN_NODE_SIZE if item and item.get("is_main") else NORMAL_NODE_SIZE


def point_near_node_edge(from_x, from_y, to_x, to_y, node_item, extra_gap=8):
    width, height = node_size_for(node_item)
    dx, dy = to_x - from_x, to_y - from_y
    half_w = width / 2 + extra_gap
    half_h = height / 2 + extra_gap
    scale_x = half_w / abs(dx) if abs(dx) else float("inf")
    scale_y = half_h / abs(dy) if abs(dy) else float("inf")
    scale = min(scale_x, scale_y, 0.48)
    return from_x + dx * scale, from_y + dy * scale


def relation_direction(value) -> str:
    return "one_way" if str(value or "").strip() == "one_way" else "both"


def merge_relation_text(existing, current, *, max_length: int) -> str:
    existing_text = str(existing or "").strip()
    current_text = str(current or "").strip()
    if not existing_text:
        return current_text[:max_length].rstrip()
    if not current_text or current_text in existing_text:
        return existing_text[:max_length].rstrip()
    return f"{existing_text} / {current_text}"[:max_length].rstrip()


def merge_duplicate_relations(relations: list[dict]) -> list[dict]:
    relation_by_pair: dict[tuple[str, str], dict] = {}
    relation_order: list[tuple[str, str]] = []

    for relation in relations:
        if not isinstance(relation, dict):
            continue

        source = str(relation.get("source") or "").strip()
        target = str(relation.get("target") or "").strip()
        if not source or not target or source == target:
            continue

        current = dict(relation)
        current["source"] = source
        current["target"] = target
        current["direction"] = relation_direction(current.get("direction"))

        pair_key = tuple(sorted((source, target)))
        if pair_key not in relation_by_pair:
            relation_by_pair[pair_key] = current
            relation_order.append(pair_key)
            continue

        existing = relation_by_pair[pair_key]
        same_order = existing.get("source") == source and existing.get("target") == target
        if existing.get("direction") == "both" or current.get("direction") == "both" or not same_order:
            existing["direction"] = "both"

        existing["relation"] = merge_relation_text(existing.get("relation"), current.get("relation"), max_length=40)
        existing["description"] = merge_relation_text(existing.get("description"), current.get("description"), max_length=240)

        if existing.get("style") == "neutral" and current.get("style") in STYLE_COLORS and current.get("style") != "neutral":
            existing["style"] = current.get("style")

        try:
            existing_importance = int(existing.get("importance", 3))
        except (TypeError, ValueError):
            existing_importance = 3
        try:
            current_importance = int(current.get("importance", 3))
        except (TypeError, ValueError):
            current_importance = 3
        existing["importance"] = max(1, min(existing_importance, current_importance, 5))

    return [relation_by_pair[key] for key in relation_order]


def node_positions(characters: list[dict]) -> dict[str, tuple[float, float]]:
    if not characters:
        return {}

    main_index = next((index for index, item in enumerate(characters) if item.get("is_main")), 0)
    center_x, center_y = GRAPH_WIDTH / 2, 430.0
    radius_x, radius_y = 470.0, 325.0
    positions = {characters[main_index]["id"]: (center_x, center_y)}
    others = [item for index, item in enumerate(characters) if index != main_index]

    for index, item in enumerate(others):
        angle = (2 * math.pi * index / max(len(others), 1)) - math.pi / 2
        positions[item["id"]] = (
            center_x + radius_x * math.cos(angle),
            center_y + radius_y * math.sin(angle),
        )
    return positions


def build_relation_html(*, work_title: str, relation_data: dict, positions: dict | None = None) -> str:
    title = esc(relation_data.get("work_title") or work_title)
    summary = esc(relation_data.get("summary", ""))
    main_character = esc(relation_data.get("main_character", ""))
    characters = relation_data.get("characters") or []
    relations = merge_duplicate_relations(relation_data.get("relations") or [])
    groups = relation_data.get("groups") or []
    warnings = relation_data.get("warnings") or []
    character_by_id = {item["id"]: item for item in characters}

    # 저장된 노드 위치 (있으면 preset 레이아웃, 없으면 breadthfirst)
    positions_json = json.dumps(positions or {}, ensure_ascii=False)

    # --- Cytoscape 노드 ---
    cy_nodes = []
    for char in characters:
        cy_nodes.append({
            "data": {
                "id": str(char["id"]),
                "name": str(char.get("name") or ""),
                "profile": str(char.get("profile_label") or ""),
                "is_main": bool(char.get("is_main")),
            }
        })

    # --- Cytoscape 엣지 ---
    cy_edges = []
    for rel in relations:
        style = rel.get("style") if rel.get("style") in STYLE_COLORS else "neutral"
        cy_edges.append({
            "data": {
                "source": str(rel.get("source") or ""),
                "target": str(rel.get("target") or ""),
                "label": str(rel.get("relation") or "")[:16],
                "color": STYLE_COLORS[style],
                "direction": relation_direction(rel.get("direction")),
            }
        })

    elements_json = json.dumps(cy_nodes + cy_edges, ensure_ascii=False)

    # --- 하단 패널 ---
    relation_items: list[str] = []
    for relation in relations:
        source = character_by_id.get(relation.get("source"), {}).get("name", relation.get("source"))
        target = character_by_id.get(relation.get("target"), {}).get("name", relation.get("target"))
        arrow = "→" if relation_direction(relation.get("direction")) == "one_way" else "↔"
        relation_items.append(
            f'<div class="item"><div class="item-title">{esc(source)} {arrow} {esc(target)} '
            f'<span class="relation-type">({esc(relation.get("relation"))})</span></div>'
            f'<div class="item-meta">{esc(relation.get("description"))}</div></div>'
        )

    group_items: list[str] = []
    for group in groups:
        chips = "".join(
            f'<span class="group-chip">{esc(character_by_id.get(member, {}).get("name", member))}</span>'
            for member in group.get("members", [])
        )
        group_items.append(
            f'<div class="item"><div class="item-title">{esc(group.get("name"))}</div>'
            f'<div>{chips}</div><div class="item-meta">{esc(group.get("description"))}</div></div>'
        )

    warning_items = "".join(f'<div class="warning">{esc(item)}</div>' for item in warnings)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    relation_panel = "".join(relation_items) or '<p class="notice">추출된 관계가 없습니다.</p>'
    group_panel = "".join(group_items) or '<p class="notice">추출된 그룹이 없습니다.</p>'

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} - 인물 관계도</title>
<script id="__rel-pos-data">window.__REL_POSITIONS__={positions_json};</script>
<style>
:root {{ --panel:#FEF9F7; --ink:#2D2440; --muted:#6E638C; --main:#6E5BB8; --lavender:#CFC3FB; --lavender-light:#E9E1FF; --shadow:0 14px 36px rgba(45,36,64,.12); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:radial-gradient(circle at top left,#fff 0,#F6F1EB 45%,#F3EEFF 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR","Malgun Gothic",sans-serif; }}
.page {{ max-width:1280px; margin:0 auto; padding:32px 24px 48px; }}
.header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:18px; }}
.kicker {{ color:#A89BD4; font-size:13px; letter-spacing:.08em; font-weight:800; }}
h1 {{ margin:6px 0 8px; font-size:34px; line-height:1.15; }}
.summary {{ margin:0; color:var(--muted); font-size:16px; line-height:1.6; }}
.badge {{ display:inline-flex; align-items:center; gap:8px; padding:10px 14px; background:rgba(254,249,247,.86); border:1px solid rgba(207,195,251,.55); border-radius:999px; box-shadow:var(--shadow); color:var(--muted); font-size:13px; white-space:nowrap; }}
.badge strong {{ color:var(--main); }}
#cy {{ position:relative; width:100%; height:{GRAPH_HEIGHT}px; background:rgba(254,249,247,.80); border:1px solid rgba(207,195,251,.50); border-radius:32px; box-shadow:var(--shadow); overflow:hidden; }}
.nc {{ position:absolute; width:152px; transform:translate(-50%,-50%); transform-origin:center center; pointer-events:none; background:linear-gradient(180deg,rgba(254,249,247,.98),rgba(249,233,250,.72)); border:1px solid rgba(207,195,251,.45); border-radius:20px; padding:13px 12px 11px; box-shadow:0 12px 28px rgba(45,36,64,.10); text-align:center; user-select:none; }}
.nc.main {{ width:180px; background:linear-gradient(180deg,#F3EEFF,#E9E1FF); border:1.5px solid #CFC3FB; box-shadow:0 18px 38px rgba(168,155,212,.34),0 8px 22px rgba(47,33,17,.10); }}
.nc-name {{ font-size:18px; font-weight:900; color:#2D2440; line-height:1.25; word-break:keep-all; }}
.nc.main .nc-name {{ font-size:20px; }}
.nc-profile {{ display:inline-block; margin-top:7px; padding:4px 10px; border-radius:999px; background:#E9E1FF; color:#6E5BB8; font-size:11px; font-weight:900; line-height:1.3; word-break:keep-all; }}
.nc.main .nc-profile {{ background:#CFC3FB; color:#2D2440; }}
.nc-profile:empty {{ display:none; }}
.content-grid {{ display:grid; grid-template-columns:minmax(0,1.2fr) minmax(320px,.8fr); gap:18px; margin-top:18px; }}
.panel {{ background:rgba(254,249,247,.86); border:1px solid rgba(207,195,251,.38); border-radius:24px; padding:18px; box-shadow:0 10px 26px rgba(45,36,64,.08); }}
.panel h2 {{ margin:0 0 12px; font-size:22px; color:var(--main); }}
.item {{ padding:12px 0; border-top:1px solid rgba(183,169,230,.28); }}
.item:first-of-type {{ border-top:0; }}
.item-title {{ font-weight:900; font-size:18px; line-height:1.45; }}
.relation-type {{ color:#A89BD4; font-weight:800; }}
.item-meta {{ margin-top:7px; color:var(--muted); font-size:17px; line-height:1.65; }}
.group-chip {{ display:inline-block; margin:4px 6px 0 0; padding:7px 11px; border-radius:999px; background:#E9E1FF; font-size:15px; font-weight:800; color:#6E5BB8; }}
.notice {{ margin-top:14px; color:var(--muted); font-size:14px; }}
.warning {{ background:#F9E9FA; border:1px solid rgba(248,215,245,.90); color:#6E5BB8; padding:10px 12px; border-radius:14px; margin-top:8px; font-size:16px; line-height:1.6; }}
@media(max-width:900px) {{ .header{{flex-direction:column;}} .content-grid{{grid-template-columns:1fr;}} }}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div><div class="kicker">HTML RELATION MAP</div><h1>{title}</h1><p class="summary">{summary}</p></div>
    <div class="badge">중심 인물 <strong>{main_character}</strong></div>
  </div>
  <div id="cy"></div>
  <div class="content-grid">
    <section class="panel"><h2>관계 목록</h2>{relation_panel}</section>
    <section class="panel"><h2>그룹/소속</h2>{group_panel}{warning_items}<p class="notice">관계도 내용은 캐릭터 설정집을 기반으로 자동 요약됩니다.</p></section>
  </div>
  <p class="notice">생성일: {created_at}</p>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script>
(function () {{
  function escHtml(s) {{
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }}

  // 저장된 위치 확인: 있으면 preset, 없으면 breadthfirst
  var savedPos = window.__REL_POSITIONS__ || {{}};
  var usePreset = Object.keys(savedPos).length > 0;

  var layoutConfig = usePreset
    ? {{
        name: 'preset',
        positions: function(node) {{ return savedPos[node.id()] || {{x: 0, y: 0}}; }},
        fit: true,
        padding: 80,
        animate: false,
      }}
    : {{
        name: 'breadthfirst',
        root: '[?is_main]',
        directed: false,
        spacingFactor: 1.6,
        padding: 80,
        animate: true,
        animationDuration: 600,
        fit: true,
        avoidOverlap: true,
      }};

  var cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: {elements_json},
    style: [
      {{
        selector: 'node',
        style: {{
          'background-opacity': 0,
          'border-width': 0,
          'label': '',
          'width': 152,
          'height': 78,
          'shape': 'round-rectangle',
        }}
      }},
      {{
        selector: 'node[?is_main]',
        style: {{
          'width': 180,
          'height': 88,
        }}
      }},
      {{
        selector: 'edge',
        style: {{
          'curve-style': 'unbundled-bezier',
          'control-point-distances': 60,
          'control-point-weights': 0.5,
          'line-color': 'data(color)',
          'target-arrow-color': 'data(color)',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 1.2,
          'width': 2.5,
          'opacity': 0.88,
          'label': 'data(label)',
          'font-size': 11,
          'font-weight': 'bold',
          'font-family': '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", "Malgun Gothic", sans-serif',
          'color': 'data(color)',
          'text-background-color': '#F6F1EB',
          'text-background-opacity': 1,
          'text-background-padding': '5px',
          'text-background-shape': 'roundrectangle',
          'text-outline-color': '#F6F1EB',
          'text-outline-width': 3,
          'text-rotation': 'autorotate',
        }}
      }},
      {{
        selector: 'edge[direction="both"]',
        style: {{
          'source-arrow-shape': 'triangle',
          'source-arrow-color': 'data(color)',
        }}
      }},
    ],
    layout: layoutConfig,
    userZoomingEnabled: true,
    userPanningEnabled: true,
    boxSelectionEnabled: false,
    autounselectify: true,
  }});

  // HTML 오버레이 카드 생성 (opacity 애니메이션 제거 — zoom:0.7 환경 대응)
  var overlay = document.createElement('div');
  overlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;visibility:hidden;';
  document.getElementById('cy').appendChild(overlay);

  cy.nodes().forEach(function(node) {{
    var d = node.data();
    var card = document.createElement('div');
    card.id = 'nc-' + node.id();
    card.className = d.is_main ? 'nc main' : 'nc';
    card.innerHTML =
      '<div class="nc-name">' + escHtml(d.name) + '</div>' +
      (d.profile ? '<div class="nc-profile">' + escHtml(d.profile) + '</div>' : '');
    overlay.appendChild(card);
  }});

  function updateCards() {{
    var zoom = cy.zoom();
    cy.nodes().forEach(function(node) {{
      var pos = node.renderedPosition();
      var card = document.getElementById('nc-' + node.id());
      if (card) {{
        card.style.left = pos.x + 'px';
        card.style.top = pos.y + 'px';
        card.style.transform = 'translate(-50%,-50%) scale(' + zoom + ')';
      }}
    }});
  }}

  // preset 레이아웃은 Cytoscape 생성 직후 매우 빨리 끝날 수 있어서
  // layoutstop 이벤트를 놓치면 카드 위치 갱신이 사용자 pan/zoom 전까지 실행되지 않는다.
  // 그래서 카드 동기화와 rel-ready 전송을 별도 안정화 함수로 분리한다.
  var layoutHandled = false;
  var relReadySent = false;

  function applyEdgeCurves() {{
    cy.edges().forEach(function(edge, i) {{
      var src = edge.source().position();
      var tgt = edge.target().position();
      var edgeLen = Math.sqrt(Math.pow(tgt.x - src.x, 2) + Math.pow(tgt.y - src.y, 2));
      var baseDist = 55 + (i % 4) * 18;
      var curveFactor = Math.min(3.5, edgeLen / 220);
      var dist = (i % 2 === 0 ? 1 : -1) * baseDist * curveFactor;
      var weight = edgeLen > 380 ? (i % 2 === 0 ? 0.22 : 0.78) : 0.33 + (i % 5) * 0.085;
      edge.style({{
        'curve-style': 'unbundled-bezier',
        'control-point-distances': dist,
        'control-point-weights': weight,
        'text-margin-y': (i % 2 === 0 ? -10 : 10),
      }});
    }});
  }}

  function runCardSyncQueue() {{
    updateCards();

    if (window.requestAnimationFrame) {{
      window.requestAnimationFrame(function() {{
        updateCards();
        window.requestAnimationFrame(function() {{
          updateCards();
        }});
      }});
    }}

    [50, 150, 300, 600].forEach(function(delay) {{
      setTimeout(updateCards, delay);
    }});
  }}

  function sendReadyAfterCardsStable() {{
    if (relReadySent) return;

    runCardSyncQueue();
    setTimeout(function() {{
      runCardSyncQueue();
      setTimeout(function() {{
        updateCards();
        overlay.style.visibility = 'visible';
        relReadySent = true;
        window.parent.postMessage({{ type: 'rel-ready' }}, '*');
      }}, 140);
    }}, usePreset ? 700 : 260);
  }}

  function finalizeLayoutOnce() {{
    if (layoutHandled) return;
    layoutHandled = true;

    // 저장된 위치 없을 때만 stagger 적용. 저장된 위치가 있으면 사용자가 옮긴 좌표를 건드리지 않는다.
    if (!usePreset) {{
      var yGroups = {{}};
      cy.nodes().forEach(function(node) {{
        var y = Math.round(node.position().y / 80) * 80;
        if (!yGroups[y]) yGroups[y] = [];
        yGroups[y].push(node);
      }});
      Object.keys(yGroups).forEach(function(y) {{
        var group = yGroups[y];
        if (group.length < 2) return;
        group.forEach(function(node, i) {{
          if (node.data('is_main')) return;
          var stagger = (i % 2 === 0 ? -1 : 1) * (30 + (i % 3) * 10);
          node.position({{ x: node.position().x, y: node.position().y + stagger }});
        }});
      }});
    }}

    applyEdgeCurves();
    cy.fit(cy.nodes(), 80);
    runCardSyncQueue();
    sendReadyAfterCardsStable();
  }}

  cy.on('layoutstop', finalizeLayoutOnce);

  cy.ready(function() {{
    // preset은 layoutstop을 놓치는 경우가 있어 ready 이후 강제로 한 번 안정화한다.
    if (usePreset) {{
      setTimeout(finalizeLayoutOnce, 0);
      setTimeout(function() {{
        if (!relReadySent) finalizeLayoutOnce();
      }}, 350);
    }} else {{
      // breadthfirst가 혹시 layoutstop을 못 보낸 경우의 마지막 안전장치
      setTimeout(function() {{
        if (!relReadySent) finalizeLayoutOnce();
      }}, 1500);
    }}
  }});

  cy.on('pan zoom render', updateCards);
  cy.on('position', 'node', updateCards);
  cy.on('free', 'node', function() {{
    var positions = {{}};
    cy.nodes().forEach(function(node) {{
      var p = node.position();
      positions[node.id()] = {{ x: Math.round(p.x), y: Math.round(p.y) }};
    }});
    window.parent.postMessage({{ type: 'rel-positions', positions: positions }}, '*');
  }});
}})();
</script>
</body>
</html>"""
