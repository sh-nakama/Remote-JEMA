"""
D3.js line chart for balancing market volume metrics.

Shows procurement (demand_mw) and contracted capacity as step lines,
with a shaded area for the gap (missing/unprocured MW).
Supports toggling any combination of volume metrics.
"""
from __future__ import annotations

import json
import streamlit.components.v1 as components

# Neutral chart accent colour (chart title, tooltip bg, expand button).
_ACCENT = "#1B2A4A"
_ACCENT_RGB = "27,42,74"


def render_volume_chart(
    data: list[dict],
    active_metrics: list[str],
    color_map: dict[str, str],
    label_map: dict[str, str],
    title: str = "Volume",
    height: int = 280,
):
    """
    Render an interactive D3.js bar/area chart for volume metrics.

    Parameters
    ----------
    data : list[dict]
        Each dict has keys: datetime (ISO str), demand_mw, contracted_mw,
        missing_mw, bids_count, contracted_count.
    active_metrics : list[str]
        Which metrics to show (e.g. ["demand_mw", "missing_mw"]).
    color_map : dict
        Metric key → hex colour.
    label_map : dict
        Metric key → display label.
    title : str
        Chart title (region name).
    height : int
        Component height in pixels.
    """
    data_json = json.dumps(data, default=str)
    color_json = json.dumps(color_map)
    label_json = json.dumps(label_map)
    active_json = json.dumps(active_metrics)

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
                max-width: 260px; opacity: 0;
                transition: opacity 0.12s; z-index: 999;
            }}
            .tooltip .tt-date {{ font-weight: 600; margin-bottom: 3px; border-bottom: 1px solid rgba(255,255,255,0.2); padding-bottom: 3px; }}
            .tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 12px; }}
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
        <div class="chart-title">{title} — Volume</div>
        <div class="chart-subtitle">Per block &nbsp;|&nbsp; Click legend to toggle</div>
        <div id="chart"></div>
        <div class="legend" id="legend"></div>
        <div class="tooltip" id="tooltip"></div>
    </div>
    <script>
    (function() {{
        const rawData = {data_json};
        const colorMap = {color_json};
        const labelMap = {label_json};
        const allMetrics = {active_json};
        const svgH = {svg_height};

        // Parse dates
        rawData.forEach(d => {{
            d._dt = new Date(d.datetime);
            allMetrics.forEach(m => {{ d[m] = +(d[m] || 0); }});
        }});

        const activeMetrics = new Set(allMetrics);

        // Separate count metrics (use secondary y-axis)
        const countMetrics = new Set(["bids_count", "contracted_count"]);
        const mwMetrics = allMetrics.filter(m => !countMetrics.has(m));
        const cntMetrics = allMetrics.filter(m => countMetrics.has(m));

        function drawChart() {{
            const isFS = !!document.fullscreenElement;
            const container = document.querySelector('.chart-container');
            d3.select("#chart").selectAll("*").remove();
            d3.select("#legend").selectAll("*").remove();

            const margin = isFS
                ? {{top: 20, right: 55, bottom: 40, left: 60}}
                : {{top: 10, right: 45, bottom: 28, left: 42}};
            const cw = container.clientWidth - 24;
            const width = Math.max(cw - margin.left - margin.right, 60);
            const chartH = isFS ? Math.max(window.innerHeight - 200, 400) : svgH;
            const innerH = chartH - margin.top - margin.bottom;
            const axisFont = isFS ? "12px" : "9px";

            // Scales
            const x = d3.scaleTime()
                .domain(d3.extent(rawData, d => d._dt))
                .range([0, width]);

            // MW y-axis (left)
            const activeMW = mwMetrics.filter(m => activeMetrics.has(m));
            const maxMW = activeMW.length > 0
                ? d3.max(rawData, d => d3.max(activeMW, m => d[m])) * 1.1
                : 100;
            const yMW = d3.scaleLinear().domain([0, maxMW]).nice().range([innerH, 0]);

            // Count y-axis (right) — only if count metrics are active
            const activeCnt = cntMetrics.filter(m => activeMetrics.has(m));
            const maxCnt = activeCnt.length > 0
                ? d3.max(rawData, d => d3.max(activeCnt, m => d[m])) * 1.1
                : 10;
            const yCnt = d3.scaleLinear().domain([0, maxCnt]).nice().range([innerH, 0]);

            const svg = d3.select("#chart").append("svg")
                .attr("width", width + margin.left + margin.right)
                .attr("height", chartH)
                .append("g")
                .attr("transform", `translate(${{margin.left}},${{margin.top}})`);

            // Grid
            svg.append("g").attr("class", "grid")
                .call(d3.axisLeft(yMW).tickSize(-width).tickFormat(""));

            // X-axis
            svg.append("g").attr("class", "axis")
                .attr("transform", `translate(0,${{innerH}})`)
                .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat("%b %d")))
                .selectAll("text").style("font-size", axisFont);

            // Left Y-axis (MW)
            svg.append("g").attr("class", "axis")
                .call(d3.axisLeft(yMW).ticks(6))
                .selectAll("text").style("font-size", axisFont);
            svg.append("text").attr("class", "y-label")
                .attr("transform", "rotate(-90)")
                .attr("y", -margin.left + 12).attr("x", -innerH / 2)
                .attr("text-anchor", "middle").text("MW");

            // Right Y-axis (count) — only if needed
            if (activeCnt.length > 0) {{
                svg.append("g").attr("class", "axis")
                    .attr("transform", `translate(${{width}},0)`)
                    .call(d3.axisRight(yCnt).ticks(5))
                    .selectAll("text").style("font-size", axisFont);
                svg.append("text").attr("class", "y-label")
                    .attr("transform", "rotate(90)")
                    .attr("y", -width - margin.right + 12).attr("x", innerH / 2)
                    .attr("text-anchor", "middle").text("Count");
            }}

            // ── Draw lines / areas ───────────────────────────────────
            const sorted = rawData.slice().sort((a,b) => a._dt - b._dt);

            // Missing MW as shaded area between demand and contracted
            if (activeMetrics.has("missing_mw") && activeMetrics.has("demand_mw")) {{
                const areaGen = d3.area()
                    .x(d => x(d._dt))
                    .y0(d => yMW(Math.min(d.demand_mw, d.contracted_mw)))
                    .y1(d => yMW(d.demand_mw))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(sorted)
                    .attr("d", areaGen)
                    .attr("fill", colorMap["missing_mw"] || "#E63946")
                    .attr("opacity", 0.25);
            }} else if (activeMetrics.has("missing_mw")) {{
                // Show missing as standalone line
                const lineGen = d3.line()
                    .defined(d => d.missing_mw != null)
                    .x(d => x(d._dt))
                    .y(d => yMW(d.missing_mw))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(sorted)
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap["missing_mw"] || "#E63946")
                    .attr("stroke-width", 1.5)
                    .attr("opacity", 0.85);
            }}

            // MW line metrics (demand_mw, contracted_mw)
            const lineMW = activeMW.filter(m => m !== "missing_mw");
            lineMW.forEach(metric => {{
                const lineGen = d3.line()
                    .defined(d => d[metric] != null)
                    .x(d => x(d._dt))
                    .y(d => yMW(d[metric]))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(sorted)
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap[metric] || "#999")
                    .attr("stroke-width", 2)
                    .attr("opacity", 0.85);
            }});

            // Count metrics as thin lines
            cntMetrics.forEach(metric => {{
                if (!activeMetrics.has(metric)) return;
                const lineGen = d3.line()
                    .defined(d => d[metric] != null)
                    .x(d => x(d._dt))
                    .y(d => yCnt(d[metric]))
                    .curve(d3.curveStepAfter);
                const sorted = rawData.slice().sort((a,b) => a._dt - b._dt);
                svg.append("path").datum(sorted)
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap[metric] || "#999")
                    .attr("stroke-width", 1.5)
                    .attr("opacity", 0.85);
            }});

            // ── Tooltip ─────────────────────────────────────────────
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
                allMetrics.forEach(m => {{
                    if (!activeMetrics.has(m)) return;
                    const c = colorMap[m] || '#999';
                    const v = (d[m] != null) ? d[m].toFixed(1) : '—';
                    html += `<div class="tt-row"><span><span class="tt-swatch" style="background:${{c}}"></span>${{labelMap[m] || m}}</span><span>${{v}}</span></div>`;
                }});
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

            // ── Legend ───────────────────────────────────────────────
            const legendEl = d3.select("#legend");
            allMetrics.forEach(m => {{
                const item = legendEl.append("div")
                    .attr("class", "legend-item" + (activeMetrics.has(m) ? "" : " muted"))
                    .on("click", () => {{
                        if (activeMetrics.has(m)) {{ activeMetrics.delete(m); }}
                        else {{ activeMetrics.add(m); }}
                        drawChart();
                    }});
                item.append("div")
                    .style("width", "10px").style("height", "10px")
                    .style("border-radius", "2px")
                    .style("background", colorMap[m] || "#999")
                    .style("flex-shrink", "0");
                item.append("span").text(labelMap[m] || m);
            }});

            // Auto-resize iframe
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
    }})();
    </script>
    </body>
    </html>
    """

    components.html(html, height=height, scrolling=False)
