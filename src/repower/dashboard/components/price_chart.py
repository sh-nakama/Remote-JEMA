"""
D3.js line chart for balancing market price metrics.

Shows max, average, and min clearing prices per block with
interactive toggle via legend clicks.
"""
from __future__ import annotations

from html import escape

import streamlit.components.v1 as components

from repower.dashboard.components._util import js_json

# Neutral chart accent colour (chart title, tooltip bg, expand button, price band).
_ACCENT = "#1B2A4A"
_ACCENT_RGB = "27,42,74"


def build_price_chart_html(
    data: list[dict],
    active_metrics: list[str],
    color_map: dict[str, str],
    label_map: dict[str, str],
    title: str = "Price",
    height: int = 280,
    subtitle: str = "¥/kW per 30min",
    y_label: str = "¥/kW·30min",
) -> str:
    """
    Build the standalone HTML document for the D3.js price line chart.

    Parameters
    ----------
    data : list[dict]
        Each dict has keys: datetime (ISO str), price_max, price_avg, price_min.
    active_metrics : list[str]
        Which metrics to show (e.g. ["price_max", "price_avg"]).
    color_map : dict
        Metric key → hex colour.
    label_map : dict
        Metric key → display label.
    title : str
        Chart title (region name).
    height : int
        Component height in pixels.
    subtitle : str
        Units caption under the title (balancing: ¥/kW·30min; wholesale: ¥/kWh).
    y_label : str
        Y-axis unit label.
    """
    data_json = js_json(data, default=str)
    color_json = js_json(color_map)
    label_json = js_json(label_map)
    active_json = js_json(active_metrics)
    y_label_json = js_json(y_label)
    title = escape(str(title))
    subtitle = escape(str(subtitle))

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
            .band {{ opacity: 0.12; }}
        </style>
    </head>
    <body>
    <div class="chart-container">
        <button class="expand-btn" id="expandBtn" title="Fullscreen">&#x26F6;</button>
        <div class="chart-title">{title} — Price</div>
        <div class="chart-subtitle">{subtitle} &nbsp;|&nbsp; Click legend to toggle</div>
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
        const accent = "{_ACCENT}";
        const yLabel = {y_label_json};

        rawData.forEach(d => {{
            d._dt = new Date(d.datetime);
            // Missing values stay null (gaps), instead of collapsing to 0.
            allMetrics.forEach(m => {{
                d[m] = (d[m] != null && Number.isFinite(+d[m])) ? +d[m] : null;
            }});
        }});
        rawData.sort((a,b) => a._dt - b._dt);

        const activeMetrics = new Set(allMetrics);

        function drawChart() {{
            const isFS = !!document.fullscreenElement;
            const container = document.querySelector('.chart-container');
            d3.select("#chart").selectAll("*").remove();
            d3.select("#legend").selectAll("*").remove();

            const margin = isFS
                ? {{top: 20, right: 30, bottom: 40, left: 60}}
                : {{top: 10, right: 14, bottom: 28, left: 42}};
            const cw = container.clientWidth - 24;
            const width = Math.max(cw - margin.left - margin.right, 60);
            const chartH = isFS ? Math.max(window.innerHeight - 200, 400) : svgH;
            const innerH = chartH - margin.top - margin.bottom;
            const axisFont = isFS ? "12px" : "9px";

            const x = d3.scaleTime()
                .domain(d3.extent(rawData, d => d._dt))
                .range([0, width]);

            const active = allMetrics.filter(m => activeMetrics.has(m));
            let yMax = active.length > 0
                ? d3.max(rawData, d => d3.max(active, m => d[m])) * 1.1
                : 10;
            if (!Number.isFinite(yMax) || yMax <= 0) yMax = 10;
            const y = d3.scaleLinear().domain([0, yMax]).nice().range([innerH, 0]);

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

            // Y-axis
            svg.append("g").attr("class", "axis")
                .call(d3.axisLeft(y).ticks(6))
                .selectAll("text").style("font-size", axisFont);
            svg.append("text").attr("class", "y-label")
                .attr("transform", "rotate(-90)")
                .attr("y", -margin.left + 12).attr("x", -innerH / 2)
                .attr("text-anchor", "middle").text(yLabel);

            // ── Shaded band between max and min ─────────────────────
            if (activeMetrics.has("price_max") && activeMetrics.has("price_min")) {{
                const band = d3.area()
                    .defined(d => d.price_min != null && d.price_max != null)
                    .x(d => x(d._dt))
                    .y0(d => y(d.price_min))
                    .y1(d => y(d.price_max))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(rawData)
                    .attr("class", "band")
                    .attr("d", band)
                    .attr("fill", accent);
            }}

            // ── Lines ───────────────────────────────────────────────
            allMetrics.forEach(m => {{
                if (!activeMetrics.has(m)) return;
                const lineGen = d3.line()
                    .defined(d => d[m] != null && !isNaN(d[m]))
                    .x(d => x(d._dt))
                    .y(d => y(d[m]))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(rawData)
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap[m] || "#999")
                    .attr("stroke-width", m === "price_avg" ? 2 : 1.5)
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

                const i = bisect(rawData, dtAtMouse, 1);
                const d0 = rawData[i-1], d1 = rawData[i];
                const d = !d1 ? d0 : (dtAtMouse - d0._dt > d1._dt - dtAtMouse ? d1 : d0);
                if (!d) {{ tooltip.style("opacity", 0); return; }}

                const dtFmt = d3.timeFormat("%Y-%m-%d %H:%M");
                let html = `<div class="tt-date">${{dtFmt(d._dt)}}</div>`;
                allMetrics.forEach(m => {{
                    if (!activeMetrics.has(m)) return;
                    const c = colorMap[m] || '#999';
                    const v = (d[m] != null) ? d[m].toFixed(2) : '—';
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
                const sw = item.append("svg").attr("width", 16).attr("height", 8);
                sw.append("line")
                    .attr("x1", 0).attr("y1", 4).attr("x2", 16).attr("y2", 4)
                    .attr("stroke", colorMap[m] || "#999").attr("stroke-width", 2);
                item.append("span").text(labelMap[m] || m);
            }});

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
    return html


def render_price_chart(
    data: list[dict],
    active_metrics: list[str],
    color_map: dict[str, str],
    label_map: dict[str, str],
    title: str = "Price",
    height: int = 280,
    subtitle: str = "¥/kW per 30min",
    y_label: str = "¥/kW·30min",
):
    """Render the price chart into the Streamlit app (see build_price_chart_html)."""
    html = build_price_chart_html(
        data, active_metrics, color_map, label_map,
        title=title, height=height, subtitle=subtitle, y_label=y_label,
    )
    components.html(html, height=height, scrolling=False)
