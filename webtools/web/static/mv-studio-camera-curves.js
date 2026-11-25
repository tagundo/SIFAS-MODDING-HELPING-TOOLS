/* Curve view of the MV Studio camera editor (MVStudioCameraCurves): a small SVG
   graph of one shot's channels. The faint line is the baked dense curve, the
   solid line the key curve; keys can be dragged (frame-snapped, value), the
   selected key's Bezier handles can be dragged (the key becomes "free"), and a
   click on the plot moves the playhead. Vertical auto-fit, frozen during a drag.

   create(container, handlers) → { update(model), element }
     handlers: onSelectKey(frame), onSeek(frame),
               onDragKey(phase "begin"|"move"|"end", { from, frame, channel, value }) → current frame,
               onDragHandle(phase, { frame, channel, side "in"|"out", handle: [dFrames, dValue] }), t(label)
     model:    { count, keys, mode, channels, dense: { channel: Float64Array }, playhead, selected, labels } */
(function (global) {
  "use strict";

  const SVG = "http://www.w3.org/2000/svg";
  const M = global.MVStudioCameraMath;
  const COLORS = Object.freeze({ x: "#ef5350", y: "#66bb6a", z: "#42a5f5", pan: "#ffb74d", tilt: "#ba68c8", roll: "#26c6da", fov: "#f06292" });
  const HEIGHT = 150, LEFT = 44, RIGHT = 8, TOP = 8, BOTTOM = 18;
  const finite = Number.isFinite;

  function node(tag, attrs = {}) {
    const element = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  }

  const shortNumber = (value) => {
    const size = Math.abs(value);
    return size >= 100 ? value.toFixed(0) : size >= 10 ? value.toFixed(1) : value.toFixed(2);
  };

  function create(container, handlers = {}) {
    const svg = node("svg", { class: "mv-cam-graph", role: "group", height: HEIGHT });
    const t = typeof handlers.t === "function" ? handlers.t : (label) => label;
    svg.setAttribute("aria-label", t("Camera curves"));
    container.replaceChildren(svg);
    let model = null, layout = null, drag = null, frozen = null, drawn = null, playheadLine = null;
    // The container's width, kept by a ResizeObserver (read after layout, where it costs
    // nothing): reading clientWidth on every playhead update forced a style and layout pass.
    let width = null;
    const resizing = global.ResizeObserver ? new global.ResizeObserver(() => {
      if (!container.isConnected) return;
      const next = container.clientWidth;
      if (next === width) return;
      width = next;
      if (model) draw();
    }) : null;
    resizing?.observe(container);

    function range(current) {
      if (frozen) return frozen;
      let low = Infinity, high = -Infinity;
      const take = (value) => { if (finite(value)) { low = Math.min(low, value); high = Math.max(high, value); } };
      for (const channel of current.channels) {
        const dense = current.dense && current.dense[channel];
        if (dense) for (const value of dense) take(value);
        for (const key of current.keys) take(key.values[channel]);
        if (current.keys.length) for (let frame = 0; frame < current.count; frame += Math.max(1, Math.floor(current.count / 120))) take(M.curve(current.keys, channel, frame));
      }
      if (!finite(low)) { low = -1; high = 1; }
      if (high - low < 1e-6) { const middle = (high + low) / 2; low = middle - 1; high = middle + 1; }
      const pad = (high - low) * .08;
      return { low: low - pad, high: high + pad };
    }

    function graphWidth() {
      return Math.max(160, Math.round((resizing && width !== null ? width : container.clientWidth) || 320));
    }

    function geometry(current) {
      const width = graphWidth();
      const { low, high } = range(current);
      const plot = { left: LEFT, top: TOP, width: width - LEFT - RIGHT, height: HEIGHT - TOP - BOTTOM };
      const last = Math.max(1, current.count - 1);
      return { width, low, high, plot, last,
        x: (frame) => plot.left + frame / last * plot.width,
        y: (value) => plot.top + (high - value) / (high - low) * plot.height,
        frame: (x) => Math.max(0, Math.min(last, (x - plot.left) / plot.width * last)),
        value: (y) => high - (y - plot.top) / plot.height * (high - low) };
    }

    function pointer(event) {
      const box = svg.getBoundingClientRect();
      return { x: (event.clientX - box.left) * layout.width / (box.width || layout.width), y: (event.clientY - box.top) * HEIGHT / (box.height || HEIGHT) };
    }

    function polyline(points, attrs) {
      return node("polyline", { points: points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" "), fill: "none", ...attrs });
    }

    function draw() {
      if (!model) return;
      layout = geometry(model);
      const { x, y, plot } = layout;
      svg.setAttribute("viewBox", `0 0 ${layout.width} ${HEIGHT}`);
      svg.setAttribute("width", layout.width);
      const parts = [];
      parts.push(node("rect", { class: "mv-cam-plot", x: plot.left, y: plot.top, width: plot.width, height: plot.height, "data-plot": "1" }));
      for (const value of [layout.high, (layout.high + layout.low) / 2, layout.low]) {
        const line = y(value);
        parts.push(node("line", { class: "mv-cam-grid", x1: plot.left, x2: plot.left + plot.width, y1: line, y2: line }));
        const label = node("text", { class: "mv-cam-axis", x: plot.left - 4, y: line + 3, "text-anchor": "end" });
        label.textContent = shortNumber(value);
        parts.push(label);
      }
      if (layout.low < 0 && layout.high > 0) parts.push(node("line", { class: "mv-cam-zero", x1: plot.left, x2: plot.left + plot.width, y1: y(0), y2: y(0) }));
      for (const [frame, anchor] of [[0, "start"], [layout.last, "end"]]) {
        const label = node("text", { class: "mv-cam-axis", x: x(frame), y: HEIGHT - 4, "text-anchor": anchor });
        label.textContent = String(Math.round(frame));
        parts.push(label);
      }
      const step = Math.max(1, Math.floor(model.count / Math.max(1, plot.width)));
      for (const channel of model.channels) {
        const color = COLORS[channel];
        const dense = model.dense && model.dense[channel];
        if (dense) {
          const points = [];
          for (let frame = 0; frame < model.count; frame += step) if (finite(dense[frame])) points.push([x(frame), y(dense[frame])]);
          if (finite(dense[model.count - 1])) points.push([x(model.count - 1), y(dense[model.count - 1])]);
          parts.push(polyline(points, { class: "mv-cam-dense", stroke: color, "data-channel": channel }));
        }
        if (model.keys.length) {
          const points = [];
          for (let frame = 0; frame < model.count; frame += step) points.push([x(frame), y(M.curve(model.keys, channel, frame))]);
          points.push([x(model.count - 1), y(M.curve(model.keys, channel, model.count - 1))]);
          parts.push(polyline(points, { class: "mv-cam-curve", stroke: color, "data-channel": channel }));
        }
      }
      // The playhead under the handles and keys, so they stay grabbable on it.
      playheadLine = null;
      if (finite(model.playhead)) {
        const px = x(Math.max(0, Math.min(layout.last, model.playhead)));
        playheadLine = node("line", { class: "mv-cam-playhead", x1: px, x2: px, y1: plot.top, y2: plot.top + plot.height });
        parts.push(playheadLine);
      }
      // Handles of the selected key (bezier segments only).
      const index = model.keys.findIndex((key) => key.frame === model.selected);
      if (index >= 0) {
        const key = model.keys[index], previous = model.keys[index - 1];
        for (const channel of model.channels) {
          const handles = M.handles(model.keys, index, channel), value = key.values[channel];
          for (const side of ["in", "out"]) {
            const used = side === "out" ? key.interp === "bezier" && index + 1 < model.keys.length
              : !!previous && previous.interp === "bezier";
            if (!used) continue;
            const [df, dv] = handles[side];
            const hx = x(key.frame + df), hy = y(value + dv);
            parts.push(node("line", { class: "mv-cam-handle-line", x1: x(key.frame), y1: y(value), x2: hx, y2: hy, stroke: COLORS[channel] }));
            parts.push(node("circle", { class: "mv-cam-handle", cx: hx, cy: hy, r: 4, fill: COLORS[channel], "data-frame": key.frame,
              "data-channel": channel, "data-side": side }));
          }
        }
      }
      for (const channel of model.channels) {
        for (const key of model.keys) {
          const cx = x(key.frame), cy = y(key.values[channel]);
          const diamond = node("path", { class: "mv-cam-curve-key" + (key.frame === model.selected ? " mv-selected" : ""),
            d: `M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z`, fill: COLORS[channel], tabindex: 0, role: "button",
            "data-frame": key.frame, "data-channel": channel,
            "aria-label": `${model.labels?.[channel] || channel} · ${t("Frame")} ${key.frame} · ${shortNumber(key.values[channel])}` });
          parts.push(diamond);
        }
      }
      svg.replaceChildren(...parts);
      drawn = { model, width: layout.width };
    }

    // The graph drawn for `previous` also shows `next` when only the playhead differs.
    function samePlot(previous, next) {
      if (!previous || previous.count !== next.count || previous.mode !== next.mode || previous.selected !== next.selected ||
          finite(previous.playhead) !== finite(next.playhead) || previous.channels.join(",") !== next.channels.join(",") ||
          JSON.stringify(previous.keys) !== JSON.stringify(next.keys) || JSON.stringify(previous.labels) !== JSON.stringify(next.labels)) return false;
      for (const channel of next.channels) {
        const a = previous.dense && previous.dense[channel], b = next.dense && next.dense[channel];
        if (a === b) continue;
        if (!a || !b || a.length !== b.length) return false;
        for (let index = 0; index < a.length; index++) if (!Object.is(a[index], b[index])) return false;
      }
      return true;
    }

    // Moves the playhead of the drawn graph (the same attributes draw() would write).
    function movePlayhead() {
      if (!playheadLine || !layout || graphWidth() !== drawn.width) return false;
      const px = layout.x(Math.max(0, Math.min(layout.last, model.playhead)));
      playheadLine.setAttribute("x1", String(px));
      playheadLine.setAttribute("x2", String(px));
      drawn = { model, width: layout.width };
      return true;
    }

    svg.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !model || !layout) return;
      const target = event.target;
      const data = target && target.dataset ? target.dataset : {};
      if (target.classList?.contains("mv-cam-curve-key")) {
        drag = { kind: "key", from: Number(data.frame), current: Number(data.frame), channel: data.channel, x: event.clientX, y: event.clientY, moved: false };
      } else if (target.classList?.contains("mv-cam-handle")) {
        drag = { kind: "handle", frame: Number(data.frame), channel: data.channel, side: data.side, x: event.clientX, y: event.clientY, moved: false };
      } else if (data.plot) {
        handlers.onSeek?.(Math.round(layout.frame(pointer(event).x)));
        return;
      } else return;
      frozen = { low: layout.low, high: layout.high };
      svg.setPointerCapture?.(event.pointerId);
      drag.pointer = event.pointerId;
      event.preventDefault();
    });

    svg.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointer !== event.pointerId || !layout) return;
      if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 3) return;
      const point = pointer(event);
      if (!drag.moved) {
        drag.moved = true;
        if (drag.kind === "key") handlers.onDragKey?.("begin", { from: drag.from });
        else handlers.onDragHandle?.("begin", { frame: drag.frame, channel: drag.channel, side: drag.side });
      }
      if (drag.kind === "key") {
        const frame = Math.round(layout.frame(point.x)), value = layout.value(point.y);
        const next = handlers.onDragKey?.("move", { from: drag.current, frame, channel: drag.channel, value });
        if (Number.isInteger(next)) drag.current = next;
      } else {
        const key = model.keys.find((item) => item.frame === drag.frame);
        if (!key) return;
        const handle = [layout.frame(point.x) - key.frame, layout.value(point.y) - key.values[drag.channel]];
        handlers.onDragHandle?.("move", { frame: drag.frame, channel: drag.channel, side: drag.side, handle });
      }
    });

    const finish = (event) => {
      if (!drag || drag.pointer !== event.pointerId) return;
      const ended = drag;
      drag = null;
      frozen = null;
      if (ended.kind === "key") {
        if (ended.moved) handlers.onDragKey?.("end", { from: ended.current });
        else handlers.onSelectKey?.(ended.from);
      } else if (ended.moved) handlers.onDragHandle?.("end", {});
      draw();
    };
    svg.addEventListener("pointerup", finish);
    svg.addEventListener("pointercancel", finish);
    svg.addEventListener("keydown", (event) => {
      const target = event.target;
      if ((event.key === "Enter" || event.key === " ") && target.classList?.contains("mv-cam-curve-key")) {
        event.preventDefault();
        handlers.onSelectKey?.(Number(target.dataset.frame));
      }
    });

    const view = {
      element: svg,
      update(next) {
        model = { ...next, keys: M.sortedKeys(next.keys), channels: (next.channels || []).filter((channel) => COLORS[channel]) };
        // While the MV plays only the playhead moves: the graph is not rebuilt.
        if (!drag && samePlot(drawn && drawn.model, model) && movePlayhead()) return;
        const focused = document.activeElement && svg.contains(document.activeElement)
          ? { frame: document.activeElement.dataset.frame, channel: document.activeElement.dataset.channel } : null;
        draw();
        if (focused) svg.querySelector(`.mv-cam-curve-key[data-frame="${focused.frame}"][data-channel="${focused.channel}"]`)?.focus({ preventScroll: true });
      },
      get dragging() { return !!drag; },
    };
    // The graph follows its container's width (the side panel can be resized); the
    // observer stops once the view is replaced.
    if (global.ResizeObserver) {
      const observer = new global.ResizeObserver(() => {
        if (!container.isConnected || container.firstChild !== svg) { observer.disconnect(); return; }
        if (model && layout && !drag && Math.max(160, Math.round(container.clientWidth || 320)) !== layout.width) view.update(model);
      });
      observer.observe(container);
    }
    return view;
  }

  global.MVStudioCameraCurves = Object.freeze({ create, COLORS, STRINGS: Object.freeze(["Camera curves", "Frame"]) });
})(typeof window !== "undefined" ? window : globalThis);
