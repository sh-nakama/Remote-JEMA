"""
D3.js multi-product price comparison chart.

Overlays price step-lines for multiple products on a single chart
so prices across products can be compared for a given region.
"""
from __future__ import annotations

import json
import uuid
import streamlit.components.v1 as components

# Neutral chart accent colour (chart title, tooltip bg, expand button).
_ACCENT = "#1B2A4A"
_ACCENT_RGB = "27,42,74"


def render_product_price_chart(
    product_data: dict[str, list[dict]],
    color_map: dict[str, str],
    metric: str = "price_avg",
    metric_label: str = "Avg Price",
    title: str = "Price",
    height: int = 300,
):
    """
    Render an interactive D3.js step-line chart comparing one price metric
    across multiple products.

    Parameters
    ----------
    product_data : dict[str, list[dict]]
        Mapping of product display label → list of records.
        Each record must have ``datetime`` (ISO str) and the chosen *metric* key.
    color_map : dict
        Product display label → hex colour.
    metric : str
        The price column to plot (``"price_avg"`` or ``"price_max"``).
    metric_label : str
        Human-readable name shown in subtitle / tooltip header.
    title : str
        Chart title (typically the region name).
    height : int
        Component height in pixels.
    """
    # Unique DOM id prefix so multiple charts on the same page don't collide
    uid = uuid.uuid4().hex[:8]

    product_json = json.dumps(
        {k: v for k, v in product_data.items()},
        default=str,
    )
    color_json = json.dumps(color_map)

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
                max-width: 300px; opacity: 0;
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
        <button class="expand-btn" id="expandBtn_{uid}" title="Fullscreen">&#x26F6;</button>
        <div class="chart-title">{title}</div>
        <div class="chart-subtitle">{metric_label} &nbsp;(¥/kW per 30min) &nbsp;|&nbsp; Click legend to toggle</div>
        <div id="chart_{uid}"></div>
        <div class="legend" id="legend_{uid}"></div>
        <div class="tooltip" id="tooltip_{uid}"></div>
    </div>
    <script>
    (function() {{
        const productData = {product_json};
        const colorMap = {color_json};
        const metric = "{metric}";
        const svgH = {svg_height};

        // Build per-product arrays with parsed dates
        const products = Object.keys(productData);
        const parsed = {{}};
        let allDates = [];
        products.forEach(p => {{
            parsed[p] = (productData[p] || []).map(d => ({{
                _dt: new Date(d.datetime),
                val: +(d[metric] || 0),
            }}));
            parsed[p].sort((a,b) => a._dt - b._dt);
            parsed[p].forEach(d => allDates.push(d._dt));
        }});
        allDates.sort((a,b) => a - b);

        const activeProducts = new Set(products);

        function drawChart() {{
            const isFS = !!document.fullscreenElement;
            const container = document.querySelector('.chart-container');
            d3.select("#chart_{uid}").selectAll("*").remove();
            d3.select("#legend_{uid}").selectAll("*").remove();

            const margin = isFS
                ? {{top: 20, right: 30, bottom: 40, left: 60}}
                : {{top: 10, right: 14, bottom: 28, left: 42}};
            const cw = container.clientWidth - 24;
            const width = Math.max(cw - margin.left - margin.right, 60);
            const chartH = isFS ? Math.max(window.innerHeight - 200, 400) : svgH;
            const innerH = chartH - margin.top - margin.bottom;
            const axisFont = isFS ? "12px" : "9px";

            const x = d3.scaleTime()
                .domain(d3.extent(allDates))
                .range([0, width]);

            const active = products.filter(p => activeProducts.has(p));
            let yMax = 10;
            active.forEach(p => {{
                const m = d3.max(parsed[p], d => d.val);
                if (m > yMax) yMax = m;
            }});
            yMax *= 1.1;
            const y = d3.scaleLinear().domain([0, yMax]).nice().range([innerH, 0]);

            const svg = d3.select("#chart_{uid}").append("svg")
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
                .attr("text-anchor", "middle").text("¥/kW·30min");

            // ── Lines (one per product) ─────────────────────────────
            products.forEach(p => {{
                if (!activeProducts.has(p)) return;
                const lineGen = d3.line()
                    .defined(d => d.val != null && !isNaN(d.val))
                    .x(d => x(d._dt))
                    .y(d => y(d.val))
                    .curve(d3.curveStepAfter);
                svg.append("path").datum(parsed[p])
                    .attr("d", lineGen)
                    .attr("fill", "none")
                    .attr("stroke", colorMap[p] || "#999")
                    .attr("stroke-width", 1.8)
                    .attr("opacity", 0.85);
            }});

            // ── Tooltip ─────────────────────────────────────────────
            const tooltip = d3.select("#tooltip_{uid}");

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

                const dtFmt = d3.timeFormat("%Y-%m-%d %H:%M");
                let html = `<div class="tt-date">${{dtFmt(dtAtMouse)}}</div>`;

                const bisect = d3.bisector(d => d._dt).left;
                products.forEach(p => {{
                    if (!activeProducts.has(p)) return;
                    const arr = parsed[p];
                    if (!arr.length) return;
                    const i = bisect(arr, dtAtMouse, 1);
                    const d0 = arr[i-1], d1 = arr[i];
                    const d = !d1 ? d0 : (dtAtMouse - d0._dt > d1._dt - dtAtMouse ? d1 : d0);
                    if (!d) return;
                    const c = colorMap[p] || '#999';
                    const v = d.val != null ? d.val.toFixed(2) : '—';
                    html += `<div class="tt-row"><span><span class="tt-swatch" style="background:${{c}}"></span>${{p}}</span><span>${{v}}</span></div>`;
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
            const legendEl = d3.select("#legend_{uid}");
            products.forEach(p => {{
                const item = legendEl.append("div")
                    .attr("class", "legend-item" + (activeProducts.has(p) ? "" : " muted"))
                    .on("click", () => {{
                        if (activeProducts.has(p)) {{ activeProducts.delete(p); }}
                        else {{ activeProducts.add(p); }}
                        drawChart();
                    }});
                const sw = item.append("svg").attr("width", 16).attr("height", 8);
                sw.append("line")
                    .attr("x1", 0).attr("y1", 4).attr("x2", 16).attr("y2", 4)
                    .attr("stroke", colorMap[p] || "#999").attr("stroke-width", 2);
                item.append("span").text(p);
            }});

            if (!isFS) {{
                const h = container.scrollHeight + 4;
                if (window.frameElement) window.frameElement.style.height = h + 'px';
            }}
        }}

        drawChart();
        document.addEventListener('fullscreenchange', () => setTimeout(drawChart, 100));
        document.getElementById('expandBtn_{uid}').addEventListener('click', function() {{
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
