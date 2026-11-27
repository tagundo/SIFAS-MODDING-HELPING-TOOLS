/* Curve view of the MV Studio camera editor (MVStudioCameraCurves): a small SVG
   graph of one shot's channels. The faint line is the baked dense curve, the
   solid line the key curve; keys can be dragged (frame-snapped, value), the
   active key's Bezier handles can be dragged (the key becomes "free"), a click on
   the plot moves the playhead and a drag on it draws a box that selects the keys
   inside (Shift: added). Shift/Ctrl/Cmd+click or Shift+Space/Enter on a key adds
   or removes it. Vertical auto-fit, frozen during a drag.

   create(container, handlers) → { update(model), element }
     handlers: onSelectKey(frame, { toggle }), onSelectKeys(frames, { add }), onSeek(frame),
               onDragKey(phase "begin"|"move"|"end", { from, frame, channel, value }) → current frame,
               onDragHandle(phase, { frame, channel, side "in"|"out", handle: [dFrames, dValue] }), t(label)
     model:    { count, keys, shape, mode, channels, dense: { channel: Float64Array }, playhead, selected (the active
                key), selection (selected frames), labels }; shape (optional): every key the curve runs
                through, keys past the shot's end included (they are not drawn as points) */
(function (global) {
  "use strict";

  const SVG = "http://www.w3.org/2000/svg";
  const M = global.MVStudioCameraMath;
  const COLORS = Object.freeze({ x: "#ef5350", y: "#66bb6a", z: "#42a5f5", pan: "#ffb74d", tilt: "#ba68c8", roll: "#26c6da", fov: "#f06292" });
  const HEIGHT = 150, LEFT = 44, RIGHT = 8, TOP = 8, BOTTOM = 18;
  const finite = Number.isFinite;
  // The width a curve view's container last had, by any view's ResizeObserver.
  let observedWidth = null;

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
    let model = null, layout = null, drag = null, frozen = null, drawn = null, playheadLine = null, boxNode = null;
    const coarse = () => !!global.matchMedia && global.matchMedia("(pointer: coarse)").matches;
    // The container's width, kept by a ResizeObserver (read after layout, where it costs
    // nothing): reading clientWidth on every playhead update forced a style and layout pass.
    let width = null;
    const resizing = global.ResizeObserver ? new global.ResizeObserver(() => {
      if (!container.isConnected) return;
      const next = container.clientWidth;
      observedWidth = next;
      if (next === width) return;
      width = next;
      // A graph already drawn at this width stays (a redraw would give the same drawing).
      if (model && !(layout && graphWidth() === layout.width)) draw();
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
        if (current.shape.length) for (let frame = 0; frame < current.count; frame += Math.max(1, Math.floor(current.count / 120))) take(M.curve(current.shape, channel, frame));
      }
      if (!finite(low)) { low = -1; high = 1; }
      if (high - low < 1e-6) { const middle = (high + low) / 2; low = middle - 1; high = middle + 1; }
      const pad = (high - low) * .08;
      return { low: low - pad, high: high + pad };
    }

    // A new view (the panel is rebuilt for every other shot) draws first at the width the
    // last view's container had: reading clientWidth there forced a style and layout pass of
    // the whole page in the middle of a click (about 57 ms with a nine-member timeline). Its
    // observer's first callback, after this frame's layout and before it is painted, redraws
    // it at the container's own width, as it already did after the first draw.
    function graphWidth() {
      const known = resizing ? width ?? observedWidth : null;
      return Math.max(160, Math.round((known ?? container.clientWidth) || 320));
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
        if (model.shape.length) {
          const points = [];
          for (let frame = 0; frame < model.count; frame += step) points.push([x(frame), y(M.curve(model.shape, channel, frame))]);
          points.push([x(model.count - 1), y(M.curve(model.shape, channel, model.count - 1))]);
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
      // Handles of the selected key (bezier segments only; the shape's keys are its neighbours).
      const index = model.shape.findIndex((key) => key.frame === model.selected && model.keys.some((item) => item.frame === key.frame));
      if (index >= 0) {
        const key = model.shape[index], previous = model.shape[index - 1];
        for (const channel of model.channels) {
          const handles = M.handles(model.shape, index, channel), value = key.values[channel];
          for (const side of ["in", "out"]) {
            const used = side === "out" ? key.interp === "bezier" && index + 1 < model.shape.length
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
      const chosen = new Set(selectionOf(model));
      // Touch screens: a 32 px circle under each point takes the tap or drag for it.
      if (coarse()) {
        for (const channel of model.channels) {
          for (const key of model.keys) {
            parts.push(node("circle", { class: "mv-cam-curve-hit", cx: x(key.frame), cy: y(key.values[channel]), r: 16,
              "aria-hidden": "true", "data-frame": key.frame, "data-channel": channel }));
          }
        }
      }
      for (const channel of model.channels) {
        for (const key of model.keys) {
          const cx = x(key.frame), cy = y(key.values[channel]), on = chosen.has(key.frame);
          const diamond = node("path", { class: "mv-cam-curve-key" + (on ? " mv-selected" : "") + (key.frame === model.selected ? " mv-cam-curve-active" : ""),
            d: `M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z`, fill: COLORS[channel], tabindex: 0, role: "button",
            "aria-pressed": String(on), "data-frame": key.frame, "data-channel": channel,
            "aria-label": `${model.labels?.[channel] || channel} · ${t("Frame")} ${key.frame} · ${shortNumber(key.values[channel])}` });
          parts.push(diamond);
        }
      }
      if (boxNode && drag && drag.kind === "box") parts.push(boxNode);
      svg.replaceChildren(...parts);
      drawn = { model, width: layout.width };
    }

    // The selected frames: the selection and the active key (always one of them).
    function selectionOf(current) {
      const frames = new Set(Array.isArray(current.selection) ? current.selection : []);
      if (finite(current.selected)) frames.add(current.selected);
      return [...frames].sort((a, b) => a - b);
    }

    // The graph drawn for `previous` also shows `next` when only the playhead differs.
    function samePlot(previous, next) {
      if (!previous || previous.count !== next.count || previous.mode !== next.mode || previous.selected !== next.selected ||
          selectionOf(previous).join(",") !== selectionOf(next).join(",") ||
          finite(previous.playhead) !== finite(next.playhead) || previous.channels.join(",") !== next.channels.join(",") ||
          JSON.stringify(previous.keys) !== JSON.stringify(next.keys) || JSON.stringify(previous.shape) !== JSON.stringify(next.shape) ||
          JSON.stringify(previous.labels) !== JSON.stringify(next.labels)) return false;
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
      const toggle = event.shiftKey || event.ctrlKey || event.metaKey;
      if (target.classList?.contains("mv-cam-curve-key") || target.classList?.contains("mv-cam-curve-hit")) {
        drag = { kind: "key", from: Number(data.frame), current: Number(data.frame), channel: data.channel, x: event.clientX, y: event.clientY, moved: false, toggle };
        // Where on the point it was taken (a finger target is wider than the point): the key keeps
        // that distance to the pointer instead of jumping under it.
        const key = model.keys.find((item) => item.frame === drag.from), at = pointer(event);
        drag.grab = key ? { x: layout.x(key.frame) - at.x, y: layout.y(key.values[drag.channel]) - at.y } : { x: 0, y: 0 };
      } else if (target.classList?.contains("mv-cam-handle")) {
        drag = { kind: "handle", frame: Number(data.frame), channel: data.channel, side: data.side, x: event.clientX, y: event.clientY, moved: false };
      } else if (data.plot) {
        // A click seeks; a drag draws a selection box.
        drag = { kind: "box", start: pointer(event), x: event.clientX, y: event.clientY, moved: false, add: event.shiftKey };
      } else return;
      frozen = { low: layout.low, high: layout.high };
      svg.setPointerCapture?.(event.pointerId);
      drag.pointer = event.pointerId;
      drag.touch = event.pointerType === "touch" || event.pointerType === "pen";
      event.preventDefault();
    });

    svg.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointer !== event.pointerId || !layout) return;
      if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < (drag.touch ? 8 : 3)) return;
      const point = pointer(event);
      if (!drag.moved) {
        drag.moved = true;
        if (drag.kind === "key") handlers.onDragKey?.("begin", { from: drag.from });
        else if (drag.kind === "handle") handlers.onDragHandle?.("begin", { frame: drag.frame, channel: drag.channel, side: drag.side });
        else { boxNode = node("rect", { class: "mv-cam-box" }); svg.append(boxNode); }
      }
      if (drag.kind === "box") {
        const clip = (value, low, high) => Math.max(low, Math.min(high, value));
        const left = clip(Math.min(drag.start.x, point.x), layout.plot.left, layout.plot.left + layout.plot.width);
        const right = clip(Math.max(drag.start.x, point.x), layout.plot.left, layout.plot.left + layout.plot.width);
        const top = clip(Math.min(drag.start.y, point.y), layout.plot.top, layout.plot.top + layout.plot.height);
        const bottom = clip(Math.max(drag.start.y, point.y), layout.plot.top, layout.plot.top + layout.plot.height);
        drag.rect = { left, right, top, bottom };
        for (const [name, value] of Object.entries({ x: left, y: top, width: right - left, height: bottom - top })) boxNode.setAttribute(name, String(value));
      } else if (drag.kind === "key") {
        const frame = Math.round(layout.frame(point.x + drag.grab.x)), value = layout.value(point.y + drag.grab.y);
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
      boxNode = null;
      if (ended.kind === "key") {
        if (ended.moved) handlers.onDragKey?.("end", { from: ended.current });
        else handlers.onSelectKey?.(ended.from, { toggle: ended.toggle });
      } else if (ended.kind === "box") {
        if (event.type === "pointerup" && ended.moved && ended.rect) handlers.onSelectKeys?.(boxed(ended.rect), { add: ended.add });
        else if (event.type === "pointerup" && !ended.moved) handlers.onSeek?.(Math.round(layout.frame(ended.start.x)));
      } else if (ended.moved) handlers.onDragHandle?.("end", {});
      draw();
    };
    // The keys whose point (any shown channel) is inside a box of the plot.
    function boxed(rect) {
      const frames = new Set();
      for (const channel of model.channels) {
        for (const key of model.keys) {
          const px = layout.x(key.frame), py = layout.y(key.values[channel]);
          if (px >= rect.left && px <= rect.right && py >= rect.top && py <= rect.bottom) frames.add(key.frame);
        }
      }
      return [...frames].sort((a, b) => a - b);
    }

    svg.addEventListener("pointerup", finish);
    svg.addEventListener("pointercancel", finish);
    svg.addEventListener("keydown", (event) => {
      const target = event.target;
      if ((event.key === "Enter" || event.key === " ") && !event.ctrlKey && !event.metaKey && !event.altKey && target.classList?.contains("mv-cam-curve-key")) {
        event.preventDefault();
        handlers.onSelectKey?.(Number(target.dataset.frame), { toggle: event.shiftKey });
      }
    });

    const view = {
      element: svg,
      update(next) {
        const keys = M.sortedKeys(next.keys);
        model = { ...next, keys, shape: Array.isArray(next.shape) ? M.sortedKeys(next.shape) : keys, channels: (next.channels || []).filter((channel) => COLORS[channel]) };
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
