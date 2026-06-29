"""
D3.js stacked-area chart for area generation mix + demand.

Renders a stacked area of generation-by-fuel layers (``stack_keys``) using
``d3.stack`` + ``d3.area`` with ``curveStepAfter``, and overlays the area-demand
series as a solid line on top. Click any legend entry to toggle that fuel layer
(the stack recomputes) or the demand line. Hover shows a tooltip with each
active series value plus a total.
"""
from __future__ import annotations

import json
import streamlit.components.v1 as components

# Neutral chart accent colour (chart title, tooltip bg, expand button, demand line).
_ACCENT = "#1B2A4A"
_ACCENT_RGB = "27,42,74"


def render_generation_chart(
    data: list[dict],
    stack_keys: list[str],
    color_map: dict,
    label_map: dict,
    demand_key: str = "area_demand_mw",
    title: str = "Supply",
    height: int = 280,
    y_label: str = "MW",
):
    """
    Render an interactive D3.js stacked-area generation-mix chart.

    Parameters
    ----------
    data : list[dict]
        Each dict has an ISO ``datetime`` string, a ``demand_key`` value, and a
        numeric value per stack key (generation-mix columns).
    stack_keys : list[str]
        Generation-mix columns to stack as fuel layers (bottom→top order).
    color_map : dict
        Stack/demand key → hex colour (falls back to a d3 ordinal palette).
    label_map : dict
        Stack/demand key → display label.
    demand_key : str
        Key for the area-demand series, drawn as a solid line over the stack.
    title : str
        Chart title (region name).
    height : int
        Component height in pixels.
    y_label : str
        Left Y-axis label.
    """
    data_json = json.dumps(data, default=str)
    color_json = json.dumps(color_map)
    label_json = json.dumps(label_map)
    stack_json = json.dumps(stack_keys)

    svg_height = height - 60

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; background: #FAFAFA; }}
            .chart-container {{ padding: 8px 10px 4px 10px; position: relative; overflow: visible; }}
            .chart-title {{ font-size: 13px; font-weight: 700; color: {_ACCENT}; margin-bottom: 2px; }}
            .chart-subtitle {{ font-size: 9px; color: #888; margin-bottom: 6px; }}
            .axis text {{ font-family: 'Inter', system-ui, sans-serif; font-size: 9px; fill: #666; }}
            .axis path, .axis line {{ stroke: #ddd; }}
            .grid line {{ stroke: #eee; stroke-dasharray: 2,3; }}
            .grid path {{ stroke-width: 0; }}
            .y-label {{ font-size: 9px; fill: #666; font-weight: 500; }}
            .legend {{
                display: flex; flex-wrap: wrap; gap: 2px 10px;
                margin-top: 4px; padding-left: 8px;
            }}
            .legend-item {{
                display: flex; align-items: center; gap: 3px;
                cursor: pointer; user-select: none;
                font-size: 9px; font-weight: 500; color: #333;
                transition: opacity 0.2s;
            }}
            .legend-item.muted {{ opacity: 0.25; }}
            .tooltip {{
                position: absolute; pointer-events: none;
                background: rgba({_ACCENT_RGB},0.92); color: #fff;
                padding: 6px 10px; border-radius: 5px;
                font-size: 11px; line-height: 1.5;
                box-shadow: 0 2px 8px rgba(0,0,0,0.18);
                max-width: 280px; opacity: 0;
                transition: opacity 0.12s; z-index: 999;
            }}
            .tooltip .tt-date {{ font-weight: 600; margin-bottom: 3px; border-bottom: 1px solid rgba(255,255,255,0.2); padding-bottom: 3px; }}
            .tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 12px; }}
            .tooltip .tt-total {{ display: flex; justify-content: space-between; gap: 12px; font-weight: 600; margin-top: 3px; border-top: 1px solid rgba(255,255,255,0.2); padding-top: 3px; }}
            .tooltip .tt-swatch {{ display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }}
            .expand-btn {{
                position: absolute; top: 4px; right: 6px;
                background: rgba({_ACCENT_RGB},0.08); border: none; border-radius: 4px;
                cursor: pointer; padding: 3px 5px; font-size: 13px; line-height: 1;
                color: {_ACCENT}; transition: background 0.15s; z-index: 10;
            }}
            .expand-btn:hover {{ background: rgba({_ACCENT_RGB},0.18); }}
        </style>
    </head>
    <body>
    <div class="chart-container">
        <button class="expand-btn" id="expandBtn" title="Fullscreen">&#x26F6;</button>
        <div class="chart-title">{title} — Generation Mix</div>
        <div class="chart-subtitle">Stacked supply &nbsp;|&nbsp; Demand overlaid &nbsp;|&nbsp; Click legend to toggle</div>
        <div id="chart"></div>
        <div class="legend" id="legend"></div>
        <div class="tooltip" id="tooltip"></div>
    </div>
    <script>
    (function() {{
        const rawData = {data_json};
        const colorMap = {color_json};
        const labelMap = {label_json};
        const stackKeys = {stack_json};
        const demandKey = {json.dumps(demand_key)};
        const yLabel = {json.dumps(y_label)};
        const accent = {json.dumps(_ACCENT)};
        const svgH = {svg_height};

        // Fallback ordinal palette for stack keys missing from colorMap.
        const fallback = d3.scaleOrdinal(d3.schemeTableau10).domain(stackKeys);
        function colorFor(k) {{ return colorMap[k] || fallback(k); }}

        // Parse dates + coerce numerics.
        rawData.forEach(d => {{
            d._dt = new Date(d.datetime);
            stackKeys.forEach(k => {{ d[k] = +(d[k] || 0); }});
            d[demandKey] = (d[demandKey] != null) ? +d[demandKey] : null;
        }});
        const sorted = rawData.slice().sort((a, b) => a._dt - b._dt);

        // Active toggle state: every fuel layer + the demand line.
        const activeStack = new Set(stackKeys);
        let demandActive = true;

        function drawChart() {{
            const isFS = !!document.fullscreenElement;
            const container = document.querySelector('.chart-container');
            d3.select("#chart").selectAll("*").remove();
            d3.select("#legend").selectAll("*").remove();

            const margin = isFS
                ? {{top: 20, right: 30, bottom: 40, left: 60}}
                : {{top: 10, right: 20, bottom: 28, left: 42}};
            const cw = container.clientWidth - 24;
            const width = Math.max(cw - margin.left - margin.right, 60);
            const chartH = isFS ? Math.max(window.innerHeight - 200, 400) : svgH;
            const innerH = chartH - margin.top - margin.bottom;
            const axisFont = isFS ? "12px" : "9px";

            const x = d3.scaleTime()
                .domain(d3.extent(sorted, d => d._dt))
                .range([0, width]);

            // Active stack layers, preserving declared order (bottom→top).
            const activeKeys = stackKeys.filter(k => activeStack.has(k));

            // Build the stack series for active layers only (re-stack on toggle).
            const stackGen = d3.stack().keys(activeKeys);
            const series = activeKeys.length ? stackGen(sorted) : [];

            // Y max = larger of top of stack and (active) demand peak.
            let maxY = 0;
            if (series.length) {{
                maxY = d3.max(series[series.length - 1], d => d[1]) || 0;
            }}
            if (demandActive) {{
                const dMax = d3.max(sorted, d => (d[demandKey] != null ? d[demandKey] : 0)) || 0;
                maxY = Math.max(maxY, dMax);
            }}
            if (maxY <= 0) maxY = 100;
            const y = d3.scaleLinear().domain([0, maxY * 1.08]).nice().range([innerH, 0]);

            const svg = d3.select("#chart").append("svg")
                .attr("width", width + margin.left + margin.right)
                .attr("height", chartH)
                .append("g")
                .attr("transform", `translate(${{margin.left}},${{margin.top}})`);

            // Grid
            svg.append("g").attr("class", "grid")
                .call(d3.axisLeft(y).tickSize(-width).tickFormat(""));

            // X-axis
            svg.append("g").attr("class", "axis")
                .attr("transform", `translate(0,${{innerH}})`)
                .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat("%b %d")))
                .selectAll("text").style("font-size", axisFont);

            // Left Y-axis
            svg.append("g").attr("class", "axis")
                .call(d3.axisLeft(y).ticks(6))
                .selectAll("text").style("font-size", axisFont);
            svg.append("text").attr("class", "y-label")
                .attr("transform", "rotate(-90)")
                .attr("y", -margin.left + 12).attr("x", -innerH / 2)
                .attr("text-anchor", "middle").text(yLabel);

            // ── Stacked areas ───────────────────────────────────────────
            const areaGen = d3.area()
                .x(d => x(d.data._dt))
                .y0(d => y(d[0]))
                .y1(d => y(d[1]))
                .curve(d3.curveStepAfter);

            svg.selectAll(".fuel-layer")
                .data(series)
                .join("path")
                .attr("class", "fuel-layer")
                .attr("d", areaGen)
                .attr("fill", d => colorFor(d.key))
                .attr("opacity", 0.85);

            // ── Demand line overlay ─────────────────────────────────────
            if (demandActive) {{
                const lineGen = d3.line()
                    .defined(d => d[demandKey] != null)
                    .x(d => x(d._dt))
                    .y(d => y(d[demandKey]))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(sorted)
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap[demandKey] || accent)
                    .attr("stroke-width", 2)
                    .attr("opacity", 0.95);
            }}

            // ── Tooltip ─────────────────────────────────────────────────
            const tooltip = d3.select("#tooltip");
            const bisect = d3.bisector(d => d._dt).left;

            const overlay = svg.append("rect")
                .attr("width", width).attr("height", innerH)
                .attr("fill", "none").attr("pointer-events", "all");

            const vertLine = svg.append("line")
                .attr("stroke", "#aaa").attr("stroke-width", 1)
                .attr("stroke-dasharray", "4,3")
                .attr("y1", 0).attr("y2", innerH).style("opacity", 0);

            overlay.on("mousemove", function(event) {{
                const [mx] = d3.pointer(event);
                const dtAtMouse = x.invert(mx);
                vertLine.attr("x1", mx).attr("x2", mx).style("opacity", 1);

                const i = bisect(sorted, dtAtMouse, 1);
                const d0 = sorted[i-1], d1 = sorted[i];
                const d = !d1 ? d0 : (dtAtMouse - d0._dt > d1._dt - dtAtMouse ? d1 : d0);
                if (!d) {{ tooltip.style("opacity", 0); return; }}

                const dtFmt = d3.timeFormat("%Y-%m-%d %H:%M");
                let html = `<div class="tt-date">${{dtFmt(d._dt)}}</div>`;
                let total = 0;
                activeKeys.forEach(k => {{
                    const c = colorFor(k);
                    const val = +(d[k] || 0);
                    total += val;
                    html += `<div class="tt-row"><span><span class="tt-swatch" style="background:${{c}}"></span>${{labelMap[k] || k}}</span><span>${{val.toFixed(1)}}</span></div>`;
                }});
                if (activeKeys.length > 1) {{
                    html += `<div class="tt-total"><span>Generation total</span><span>${{total.toFixed(1)}}</span></div>`;
                }}
                if (demandActive) {{
                    const c = colorMap[demandKey] || accent;
                    const dv = (d[demandKey] != null) ? d[demandKey].toFixed(1) : '—';
                    html += `<div class="tt-row"><span><span class="tt-swatch" style="background:${{c}}"></span>${{labelMap[demandKey] || demandKey}}</span><span>${{dv}}</span></div>`;
                }}
                tooltip.html(html).style("opacity", 1);
                const ttNode = tooltip.node();
                const ttWidth = ttNode.offsetWidth || 200;
                const containerWidth = container.clientWidth;
                const cursorX = event.pageX;
                const spaceRight = containerWidth - cursorX;
                if (spaceRight < ttWidth + 20) {{
                    tooltip.style("left", (cursorX - ttWidth - 12) + "px");
                }} else {{
                    tooltip.style("left", (cursorX + 12) + "px");
                }}
                tooltip.style("top", (event.pageY - 16) + "px");
            }});
            overlay.on("mouseleave", function() {{
                tooltip.style("opacity", 0);
                vertLine.style("opacity", 0);
            }});

            // ── Legend (fuel layers + demand line) ──────────────────────
            const legendEl = d3.select("#legend");
            stackKeys.forEach(k => {{
                const item = legendEl.append("div")
                    .attr("class", "legend-item" + (activeStack.has(k) ? "" : " muted"))
                    .on("click", () => {{
                        if (activeStack.has(k)) {{ activeStack.delete(k); }}
                        else {{ activeStack.add(k); }}
                        drawChart();
                    }});
                item.append("div")
                    .style("width", "10px").style("height", "10px")
                    .style("border-radius", "2px")
                    .style("background", colorFor(k))
                    .style("flex-shrink", "0");
                item.append("span").text(labelMap[k] || k);
            }});
            // Demand line legend entry.
            const dItem = legendEl.append("div")
                .attr("class", "legend-item" + (demandActive ? "" : " muted"))
                .on("click", () => {{ demandActive = !demandActive; drawChart(); }});
            dItem.append("div")
                .style("width", "10px").style("height", "10px")
                .style("border-radius", "2px")
                .style("background", colorMap[demandKey] || accent)
                .style("flex-shrink", "0");
            dItem.append("span").text(labelMap[demandKey] || demandKey);

            // Auto-resize iframe.
            if (!isFS) {{
                const h = container.scrollHeight + 4;
                if (window.frameElement) window.frameElement.style.height = h + 'px';
            }}
        }}

        drawChart();
        document.addEventListener('fullscreenchange', () => setTimeout(drawChart, 100));
        document.getElementById('expandBtn').addEventListener('click', function() {{
            const el = document.documentElement;
            if (!document.fullscreenElement) {{
                (el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen).call(el);
                document.body.style.background = '#fff';
            }} else {{
                (document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen).call(document);
            }}
        }});

        // Redraw on container resize (mirrors volume_chart auto-resize).
        if (window.ResizeObserver) {{
            const ro = new ResizeObserver(() => {{ if (!document.fullscreenElement) drawChart(); }});
            ro.observe(document.querySelector('.chart-container'));
        }}
    }})();
    </script>
    </body>
    </html>
    """

    components.html(html, height=height, scrolling=False)
