"""
D3.js line chart for interconnector (tieline) reserved volumes.

Shows upper limits as dashed step lines and reserved volumes as solid
step lines with shaded fill underneath, for both forward and reverse
directions on a single chart per interconnector pair.
"""
from __future__ import annotations

from html import escape

import streamlit.components.v1 as components

from repower.dashboard.components._util import js_json

# Neutral chart accent colour (chart title, tooltip bg, expand button).
_ACCENT = "#1B2A4A"
_ACCENT_RGB = "27,42,74"


def build_tieline_chart_html(
    data: list[dict],
    active_metrics: list[str],
    color_map: dict[str, str],
    label_map: dict[str, str],
    title: str = "Interconnector",
    height: int = 280,
    lang: str = "en",
) -> str:
    """
    Build the standalone HTML document for the D3.js tieline chart.

    Parameters
    ----------
    data : list[dict]
        Each dict has keys: datetime (ISO str), upper_limit_fwd,
        upper_limit_rev, reserved_fwd, reserved_rev.
    active_metrics : list[str]
        Which metrics to show.
    color_map : dict
        Metric key → hex colour.
    label_map : dict
        Metric key → display label.
    title : str
        Chart title (interconnector pair name — DB-derived, so escaped).
    height : int
        Component height in pixels.
    lang : str
        Language code ("en" or "ja").
    """
    data_json = js_json(data, default=str)
    color_json = js_json(color_map)
    label_json = js_json(label_map)
    active_json = js_json(active_metrics)
    lang_json = js_json(lang)
    title = escape(str(title))

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
            body {{ font-family: 'Inter', 'Yu Gothic', 'Segoe UI', system-ui, sans-serif; background: #FAFAFA; }}
            .chart-container {{ padding: 8px 10px 4px 10px; position: relative; overflow: visible; }}
            .chart-title {{ font-size: 13px; font-weight: 700; color: {_ACCENT}; margin-bottom: 2px; }}
            .chart-subtitle {{ font-size: 9px; color: #888; margin-bottom: 6px; }}
            .axis text {{ font-family: 'Inter', 'Yu Gothic', system-ui, sans-serif; font-size: 9px; fill: #666; }}
            .axis path, .axis line {{ stroke: #ddd; }}
            .grid line {{ stroke: #eee; stroke-dasharray: 2,3; }}
            .grid path {{ stroke-width: 0; }}
            .y-label {{ font-size: 9px; fill: #666; font-weight: 500; }}
            .legend {{
                display: flex; flex-wrap: wrap; gap: 4px 16px;
                margin-top: 6px; padding-left: 8px;
            }}
            .legend-item {{
                display: flex; align-items: center; gap: 5px;
                cursor: pointer; user-select: none;
                font-size: 12px; font-weight: 500; color: #333;
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
        <div class="chart-title">{title}</div>
        <div class="chart-subtitle">Per block &nbsp;|&nbsp; Dashed = upper limit &nbsp;|&nbsp; Click legend to toggle</div>
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
        const lang = {lang_json};

        // Japanese date formats for axis labels
        function fmtDateAxis(d) {{
            if (lang === "ja") {{ return (d.getMonth()+1) + "月" + d.getDate() + "日"; }}
            return d3.timeFormat("%b %d")(d);
        }}
        function fmtDateTooltip(d) {{
            if (lang === "ja") {{ return d.getFullYear() + "/" + (d.getMonth()+1) + "/" + d.getDate() + " " + String(d.getHours()).padStart(2,"0") + ":" + String(d.getMinutes()).padStart(2,"0"); }}
            return d3.timeFormat("%Y-%m-%d %H:%M")(d);
        }}

        rawData.forEach(d => {{
            d._dt = new Date(d.datetime);
            // Missing values stay null (gaps), instead of collapsing to 0.
            allMetrics.forEach(m => {{
                d[m] = (d[m] != null && Number.isFinite(+d[m])) ? +d[m] : null;
            }});
        }});

        const activeMetrics = new Set(allMetrics);

        // Upper limit metrics are shown as dashed lines
        const limitMetrics = new Set(["upper_limit_fwd", "upper_limit_rev"]);

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
                .domain(d3.extent(rawData, d => d._dt))
                .range([0, width]);

            const activeArr = allMetrics.filter(m => activeMetrics.has(m));
            let maxVal = activeArr.length > 0
                ? d3.max(rawData, d => d3.max(activeArr, m => d[m])) * 1.1
                : 100;
            if (!Number.isFinite(maxVal) || maxVal <= 0) maxVal = 100;
            const y = d3.scaleLinear().domain([0, maxVal]).nice().range([innerH, 0]);

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
                .call(d3.axisBottom(x).ticks(6).tickFormat(fmtDateAxis))
                .selectAll("text").style("font-size", axisFont);

            // Y-axis
            svg.append("g").attr("class", "axis")
                .call(d3.axisLeft(y).ticks(6))
                .selectAll("text").style("font-size", axisFont);
            svg.append("text").attr("class", "y-label")
                .attr("transform", "rotate(-90)")
                .attr("y", -margin.left + 12).attr("x", -innerH / 2)
                .attr("text-anchor", "middle").text("MW");

            const sorted = rawData.slice().sort((a,b) => a._dt - b._dt);

            // Draw shaded area under reserved metrics
            ["reserved_fwd", "reserved_rev"].forEach(metric => {{
                if (!activeMetrics.has(metric)) return;
                const areaGen = d3.area()
                    .defined(d => d[metric] != null)
                    .x(d => x(d._dt))
                    .y0(innerH)
                    .y1(d => y(d[metric]))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(sorted)
                    .attr("d", areaGen)
                    .attr("fill", colorMap[metric] || "#999")
                    .attr("opacity", 0.18);
            }});

            // Draw lines for each active metric
            activeArr.forEach(metric => {{
                const lineGen = d3.line()
                    .defined(d => d[metric] != null)
                    .x(d => x(d._dt))
                    .y(d => y(d[metric]))
                    .curve(d3.curveStepAfter);
                const path = svg.append("path").datum(sorted)
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap[metric] || "#999")
                    .attr("stroke-width", limitMetrics.has(metric) ? 1.5 : 2)
                    .attr("opacity", 0.85);
                if (limitMetrics.has(metric)) {{
                    path.attr("stroke-dasharray", "6,3");
                }}
            }});

            // Tooltip
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

                let html = `<div class="tt-date">${{fmtDateTooltip(d._dt)}}</div>`;
                allMetrics.forEach(m => {{
                    if (!activeMetrics.has(m)) return;
                    const c = colorMap[m] || '#999';
                    const v = (d[m] != null) ? d[m].toFixed(1) : '—';
                    const prefix = limitMetrics.has(m) ? '┄ ' : '━ ';
                    html += `<div class="tt-row"><span>${{prefix}}<span class="tt-swatch" style="background:${{c}}"></span>${{labelMap[m] || m}}</span><span>${{v}}</span></div>`;
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

            // Legend
            const legendEl = d3.select("#legend");
            allMetrics.forEach(m => {{
                const item = legendEl.append("div")
                    .attr("class", "legend-item" + (activeMetrics.has(m) ? "" : " muted"))
                    .on("click", () => {{
                        if (activeMetrics.has(m)) {{ activeMetrics.delete(m); }}
                        else {{ activeMetrics.add(m); }}
                        drawChart();
                    }});
                const swatch = item.append("div")
                    .style("width", "14px").style("height", "14px")
                    .style("border-radius", "3px")
                    .style("background", colorMap[m] || "#999")
                    .style("flex-shrink", "0");
                if (limitMetrics.has(m)) {{
                    swatch.style("border", "1px dashed " + (colorMap[m] || "#999"))
                           .style("background", "transparent");
                }}
                item.append("span").text(labelMap[m] || m);
            }});

            if (!isFS) {{
                const h = container.scrollHeight + 4;
                if (window.frameElement) window.frameElement.style.height = h + 'px';
            }}
        }}

        drawChart();
        document.addEventListener('fullscreenchange', () => setTimeout(drawChart, 100));

        // Redraw when container becomes visible (e.g. Streamlit tab switch)
        let lastW = 0;
        const ro = new ResizeObserver(() => {{
            const w = document.querySelector('.chart-container').clientWidth;
            if (w > 0 && w !== lastW) {{ lastW = w; drawChart(); }}
        }});
        ro.observe(document.querySelector('.chart-container'));

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
    return html


def render_tieline_chart(
    data: list[dict],
    active_metrics: list[str],
    color_map: dict[str, str],
    label_map: dict[str, str],
    title: str = "Interconnector",
    height: int = 280,
    lang: str = "en",
):
    """Render the tieline chart into the Streamlit app (see build_tieline_chart_html)."""
    html = build_tieline_chart_html(
        data, active_metrics, color_map, label_map,
        title=title, height=height, lang=lang,
    )
    components.html(html, height=height, scrolling=False)
