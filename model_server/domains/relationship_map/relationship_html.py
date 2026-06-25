import html
import math
from datetime import datetime


GRAPH_WIDTH = 1180
GRAPH_HEIGHT = 860
NORMAL_NODE_SIZE = (184, 84)
MAIN_NODE_SIZE = (222, 100)

STYLE_COLORS = {
    "romance": "#b56b82",
    "partnership": "#6c8a62",
    "hierarchy": "#7562a0",
    "rivalry": "#c95b4a",
    "mentorship": "#8a6bbb",
    "family": "#b8844c",
    "organization": "#5d7c99",
    "neutral": "#b99b72",
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


def build_relation_html(*, work_title: str, relation_data: dict) -> str:
    title = esc(relation_data.get("work_title") or work_title)
    summary = esc(relation_data.get("summary", ""))
    main_character = esc(relation_data.get("main_character", ""))
    characters = relation_data.get("characters") or []
    relations = merge_duplicate_relations(relation_data.get("relations") or [])
    groups = relation_data.get("groups") or []
    warnings = relation_data.get("warnings") or []
    positions = node_positions(characters)
    character_by_id = {item["id"]: item for item in characters}

    marker_defs = "".join(
        f'<marker id="arrow-{style}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}" /></marker>'
        for style, color in STYLE_COLORS.items()
    )

    edge_paths: list[str] = []
    for index, relation in enumerate(relations):
        source_point = positions.get(relation.get("source"))
        target_point = positions.get(relation.get("target"))
        if not source_point or not target_point:
            continue

        raw_x1, raw_y1 = source_point
        raw_x2, raw_y2 = target_point
        source_item = character_by_id.get(relation.get("source"))
        target_item = character_by_id.get(relation.get("target"))
        x1, y1 = point_near_node_edge(raw_x1, raw_y1, raw_x2, raw_y2, source_item)
        x2, y2 = point_near_node_edge(raw_x2, raw_y2, raw_x1, raw_y1, target_item)
        style = relation.get("style") if relation.get("style") in STYLE_COLORS else "neutral"
        color = STYLE_COLORS[style]
        direction = relation_direction(relation.get("direction"))
        marker = f' marker-end="url(#arrow-{style})"'
        if direction == "both":
            marker = f' marker-start="url(#arrow-{style})" marker-end="url(#arrow-{style})"'

        dx, dy = x2 - x1, y2 - y1
        distance = max(math.hypot(dx, dy), 1)
        curve_strength = 18 + (index % 3) * 5
        curve_direction = -1 if index % 2 else 1
        control_x = (x1 + x2) / 2 + (-dy / distance) * curve_strength * curve_direction
        control_y = (y1 + y2) / 2 + (dx / distance) * curve_strength * curve_direction
        edge_paths.append(
            f'<path class="edge-line edge-{direction}" d="M {x1:.1f} {y1:.1f} Q {control_x:.1f} {control_y:.1f} {x2:.1f} {y2:.1f}" stroke="{color}"{marker}></path>'
        )

    node_cards: list[str] = []
    for item in characters:
        x, y = positions.get(item["id"], (GRAPH_WIDTH / 2, 430.0))
        class_name = "node main" if item.get("is_main") else "node"
        node_cards.append(
            f'<article class="{class_name}" style="left:{x:.1f}px; top:{y:.1f}px;">'
            f'<div class="name">{esc(item.get("name"))}</div>'
            f'<div class="profile-label">{esc(item.get("profile_label"))}</div>'
            f"</article>"
        )

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

    legend_items = "".join(
        f'<span class="legend-item"><i style="background:{color};"></i>{esc(STYLE_LABELS.get(style, style))}</span>'
        for style, color in STYLE_COLORS.items()
    )
    warning_items = "".join(f'<div class="warning">{esc(item)}</div>' for item in warnings)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} - 인물 관계도</title>
<style>
:root {{ --bg:#F6F1EB; --panel:#FEF9F7; --ink:#2D2440; --muted:#6E638C; --main:#6E5BB8; --lavender:#CFC3FB; --lavender-light:#E9E1FF; --lavender-pale:#F3EEFF; --pink-white:#F9E9FA; --shadow:0 14px 36px rgba(45,36,64,.12); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:radial-gradient(circle at top left,#fff 0,#F6F1EB 45%,#F3EEFF 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR","Malgun Gothic",sans-serif; }}
.page {{ max-width:1280px; margin:0 auto; padding:32px 24px 48px; }}
.header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:18px; }}
.kicker {{ color:#A89BD4; font-size:13px; letter-spacing:.08em; font-weight:800; }}
h1 {{ margin:6px 0 8px; font-size:34px; line-height:1.15; }}
.summary {{ margin:0; color:var(--muted); font-size:16px; line-height:1.6; }}
.badge {{ display:inline-flex; align-items:center; gap:8px; padding:10px 14px; background:rgba(254,249,247,.86); border:1px solid rgba(207,195,251,.55); border-radius:999px; box-shadow:var(--shadow); color:var(--muted); font-size:13px; white-space:nowrap; }}
.badge strong {{ color:var(--main); }}
.graph-card {{ position:relative; width:100%; min-height:{GRAPH_HEIGHT}px; background:rgba(254,249,247,.80); border:1px solid rgba(207,195,251,.50); border-radius:32px; overflow:auto; box-shadow:var(--shadow); }}
.graph-inner {{ position:relative; width:{GRAPH_WIDTH}px; height:{GRAPH_HEIGHT}px; transform-origin:top left; }}
.lines {{ position:absolute; inset:0; width:{GRAPH_WIDTH}px; height:{GRAPH_HEIGHT}px; z-index:1; }}
.node {{ position:absolute; width:{NORMAL_NODE_SIZE[0]}px; min-height:{NORMAL_NODE_SIZE[1]}px; transform:translate(-50%,-50%); z-index:2; background:linear-gradient(180deg,rgba(254,249,247,.98),rgba(249,233,250,.72)); border:1px solid rgba(207,195,251,.45); border-radius:20px; padding:15px 14px 13px; box-shadow:0 12px 28px rgba(45,36,64,.10); text-align:center; }}
.node.main {{ width:{MAIN_NODE_SIZE[0]}px; min-height:{MAIN_NODE_SIZE[1]}px; background:linear-gradient(180deg,var(--lavender-pale),var(--lavender-light)); border:1px solid var(--lavender); box-shadow:0 18px 38px rgba(168,155,212,.34),0 8px 22px rgba(47,33,17,.10); }}
.name {{ font-size:20px; font-weight:900; line-height:1.25; word-break:keep-all; }}
.node.main .name {{ font-size:21px; color:var(--ink); }}
.profile-label {{ display:inline-block; margin-top:9px; max-width:100%; padding:6px 12px; border-radius:999px; background:#E9E1FF; color:#6E5BB8; font-size:13px; font-weight:900; line-height:1.25; word-break:keep-all; }}
.node.main .profile-label {{ background:var(--lavender); color:#2D2440; }}
.profile-label:empty {{ display:none; }}
.edge-line {{ fill:none; stroke-linecap:round; opacity:.95; }}
.edge-one_way {{ stroke-width:3.0; }}
.edge-both {{ stroke-width:3.1; opacity:.82; }}
.content-grid {{ display:grid; grid-template-columns:minmax(0,1.2fr) minmax(320px,.8fr); gap:18px; margin-top:18px; }}
.panel {{ background:rgba(254,249,247,.86); border:1px solid rgba(207,195,251,.38); border-radius:24px; padding:18px; box-shadow:0 10px 26px rgba(45,36,64,.08); }}
.panel h2 {{ margin:0 0 12px; font-size:20px; color:var(--main); }}
.item {{ padding:12px 0; border-top:1px solid rgba(183,169,230,.28); }}
.item:first-of-type {{ border-top:0; }}
.item-title {{ font-weight:900; font-size:16px; }}
.relation-type {{ color:#A89BD4; font-weight:800; }}
.item-meta {{ margin-top:4px; color:var(--muted); font-size:15px; line-height:1.55; }}
.group-chip {{ display:inline-block; margin:4px 6px 0 0; padding:6px 10px; border-radius:999px; background:#E9E1FF; font-size:13px; font-weight:800; color:#6E5BB8; }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:12px; color:var(--muted); font-size:13px; }}
.legend-item {{ display:inline-flex; align-items:center; gap:5px; white-space:nowrap; }}
.legend-item i {{ width:18px; height:3px; border-radius:999px; display:inline-block; opacity:.88; }}
.notice {{ margin-top:14px; color:var(--muted); font-size:13px; }}
.warning {{ background:#F9E9FA; border:1px solid rgba(248,215,245,.90); color:#6E5BB8; padding:10px 12px; border-radius:14px; margin-top:8px; font-size:14px; line-height:1.5; }}
@media(max-width:900px) {{ .header{{flex-direction:column;}} .content-grid{{grid-template-columns:1fr;}} }}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div><div class="kicker">HTML RELATION MAP</div><h1>{title}</h1><p class="summary">{summary}</p></div>
    <div class="badge">중심 인물 <strong>{main_character}</strong></div>
  </div>
  <section class="graph-card"><div class="graph-inner"><svg class="lines" viewBox="0 0 {GRAPH_WIDTH} {GRAPH_HEIGHT}" aria-hidden="true"><defs>{marker_defs}</defs>{''.join(edge_paths)}</svg>{''.join(node_cards)}</div></section>
  <div class="legend" aria-label="관계 색상 범례">{legend_items}</div>
  <div class="content-grid">
    <section class="panel"><h2>관계 목록</h2>{''.join(relation_items) or '<p class="notice">추출된 관계가 없습니다.</p>'}</section>
    <section class="panel"><h2>그룹/소속</h2>{''.join(group_items) or '<p class="notice">추출된 그룹이 없습니다.</p>'}{warning_items}<p class="notice">관계도 내용은 캐릭터 설정집을 기반으로 자동 요약됩니다.</p></section>
  </div>
  <p class="notice">생성일: {created_at}</p>
</div>
</body>
</html>"""
