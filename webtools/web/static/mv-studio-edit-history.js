/* Undo/redo history of MV Studio edits.

   Every write the editor makes to the open project goes through one history:
   a command is a list of changes on targets that are resolved by id against
   the current project each time (never cached objects), so an entry stays
   valid across a project reload with the same ids and becomes inert when its
   target is gone. The first change to a timeline event keeps a deep copy of
   that event in project.editor.originals, which is what "edited" and "revert"
   compare against. project.editor is only created by the first real change. */
(function (global) {
  "use strict";

  const own = (object, key) => object != null && Object.prototype.hasOwnProperty.call(object, key);
  const clone = (value) => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  const isObject = (value) => value !== null && typeof value === "object";

  // JSON with sorted object keys: equal data gives equal text whatever the key order.
  function stable(value) {
    if (value === undefined) return "undefined";
    if (!isObject(value)) return JSON.stringify(value);
    if (Array.isArray(value)) return "[" + value.map((item) => item === undefined ? "null" : stable(item)).join(",") + "]";
    return "{" + Object.keys(value).filter((key) => value[key] !== undefined).sort()
      .map((key) => JSON.stringify(key) + ":" + stable(value[key])).join(",") + "}";
  }

  // The part of an event that decides "edited" (spec §1); editableValues is left out on purpose.
  function editedView(event) {
    return event ? { start: event.start, duration: event.duration, label: event.label, values: event.values } : null;
  }

  function hollow(value) {
    return isObject(value) && Object.keys(value).every((key) => hollow(value[key]));
  }

  function sameTarget(first, second) {
    return stable(first) === stable(second);
  }

  function changeKey(change) {
    return stable({ target: change.target, path: change.path });
  }

  function create(options = {}) {
    const getProject = typeof options.getProject === "function" ? options.getProject : () => null;
    const onChange = typeof options.onChange === "function" ? options.onChange : () => {};
    const limit = Number.isInteger(options.limit) && options.limit > 0 ? options.limit : 200;
    // compareView(track, event) → the object compared for "edited"; defaults to editedView(event).
    const compareView = typeof options.compareView === "function" ? options.compareView : (_track, event) => editedView(event);
    let undoStack = [], redoStack = [], version = 0, depth = 0, gesture = null;
    let editedCache = null, editedKey = null;

    function project() {
      const value = getProject();
      return value && Array.isArray(value.tracks) ? value : null;
    }

    function editorOf(value, make) {
      if (!value) return null;
      if (!isObject(value.editor)) {
        if (!make) return null;
        value.editor = { version: 1, originals: {} };
      }
      if (make && !isObject(value.editor.originals)) value.editor.originals = {};
      return value.editor;
    }

    function findEvent(value, id) {
      if (!value) return null;
      for (const track of value.tracks) {
        const event = Array.isArray(track.events) ? track.events.find((item) => item && item.id === id) : null;
        if (event) return { track, event };
      }
      return null;
    }

    function resolve(value, target, make) {
      if (!value || !isObject(target)) return null;
      switch (target.kind) {
        case "event": {
          const track = value.tracks.find((item) => item.id === target.track);
          return track && Array.isArray(track.events) ? track.events.find((item) => item && item.id === target.event) || null : null;
        }
        case "track": return value.tracks.find((item) => item.id === target.track) || null;
        case "editor": return editorOf(value, make);
        case "performer": return (value.performers || []).find((item) => item && item.id === target.id) || null;
        case "soundtrack": return isObject(value.soundtrack) ? value.soundtrack : null;
        case "quality": return isObject(value.quality) ? value.quality : null;
        default: return null;
      }
    }

    // Walks to the parent of the last path segment. With make, missing containers
    // are created; the index of the first one created is returned for undo.
    function walk(root, path, make) {
      let node = root, created = -1;
      for (let index = 0; index < path.length - 1; index++) {
        const key = path[index];
        if (!isObject(node[key])) {
          if (!make) return null;
          node[key] = typeof path[index + 1] === "number" ? [] : {};
          if (created < 0) created = index;
        }
        node = node[key];
      }
      return { parent: node, leaf: path[path.length - 1], created };
    }

    function originalsEnsure(id, value = project()) {
      const found = findEvent(value, id);
      if (!found) return null;
      const editor = editorOf(value, true);
      if (!own(editor.originals, id)) editor.originals[id] = clone(found.event);
      return editor.originals[id];
    }

    function normalize(command) {
      if (!isObject(command) || !Array.isArray(command.changes) || !command.changes.length) return null;
      const changes = [];
      for (const raw of command.changes) {
        if (!isObject(raw) || !isObject(raw.target) || !Array.isArray(raw.path)) return null;
        const op = raw.op || "set";
        if (!["set", "insert", "remove"].includes(op)) return null;
        if (op === "set" && !raw.path.length) return null;
        const change = { target: clone(raw.target), path: raw.path.slice(), op };
        if (op === "set") {
          change.after = clone(raw.after);
          if (own(raw, "before")) { change.before = clone(raw.before); change.given = true; }
        } else {
          change.index = raw.index;
          if (own(raw, "value")) change.value = clone(raw.value);
        }
        changes.push(change);
      }
      return { label: typeof command.label === "string" && command.label ? command.label : "Edit",
        detail: typeof command.detail === "string" ? command.detail : "", changes,
        coalesce: typeof command.coalesce === "string" && command.coalesce ? command.coalesce : null };
    }

    function container(value, change, make) {
      const root = resolve(value, change.target, make);
      if (!root) return null;
      if (change.op === "set") return walk(root, change.path, make);
      let array = root;
      for (const key of change.path) array = isObject(array) ? array[key] : undefined;
      return Array.isArray(array) ? { array } : null;
    }

    // True when applying the change would modify the project.
    function effective(value, change) {
      const place = container(value, change, false);
      if (change.op === "set") {
        if (change.given) return stable(change.before) !== stable(change.after);
        // A missing container is created by the write; an editor target is created on first use.
        if (!place) return change.after !== undefined && (change.target.kind === "editor" || !!resolve(value, change.target, false));
        const had = own(place.parent, place.leaf);
        return had ? stable(place.parent[place.leaf]) !== stable(change.after) : change.after !== undefined;
      }
      if (!place) return false;
      const index = change.index;
      if (!Number.isInteger(index) || index < 0) return false;
      return change.op === "insert" ? index <= place.array.length : index < place.array.length;
    }

    // Applies one change forward and records what undo needs on the change.
    function forward(value, change) {
      if (change.target.kind === "event") originalsEnsure(change.target.event, value);
      if (change.op === "set") {
        const place = container(value, change, change.after !== undefined);
        if (!place) return false;
        const had = own(place.parent, place.leaf);
        if (!change.given) { change.before = had ? clone(place.parent[place.leaf]) : undefined; }
        change.had = change.given ? change.before !== undefined : had;
        change.created = place.created;
        if (change.after === undefined) {
          if (Array.isArray(place.parent)) place.parent[place.leaf] = undefined;
          else delete place.parent[place.leaf];
        } else place.parent[place.leaf] = clone(change.after);
        return true;
      }
      const place = container(value, change, false);
      if (!place) return false;
      if (change.op === "insert") {
        if (!Number.isInteger(change.index) || change.index < 0 || change.index > place.array.length) return false;
        place.array.splice(change.index, 0, clone(change.value));
        // An event the editor added has no native original: originals[id] = null marks it.
        if (change.target.kind === "track" && change.path.length === 1 && change.path[0] === "events" &&
            isObject(change.value) && typeof change.value.id === "string") {
          const editor = editorOf(value, true);
          if (!own(editor.originals, change.value.id)) editor.originals[change.value.id] = null;
        }
        return true;
      }
      if (!Number.isInteger(change.index) || change.index < 0 || change.index >= place.array.length) return false;
      change.value = clone(place.array[change.index]);
      place.array.splice(change.index, 1);
      return true;
    }

    function backward(value, change) {
      if (change.op === "set") {
        const place = container(value, change, change.had);
        if (!place) return false;
        if (change.had) place.parent[place.leaf] = clone(change.before);
        else if (Array.isArray(place.parent)) place.parent[place.leaf] = undefined;
        else delete place.parent[place.leaf];
        if (change.created >= 0) {
          const root = resolve(value, change.target, false);
          const holder = root && walk(root, change.path.slice(0, change.created + 1), false);
          if (holder && hollow(holder.parent[holder.leaf])) delete holder.parent[holder.leaf];
        }
        return true;
      }
      const place = container(value, change, false);
      if (!place) return false;
      if (change.op === "insert") {
        if (change.index >= place.array.length) return false;
        place.array.splice(change.index, 1);
      } else {
        if (change.index > place.array.length) return false;
        place.array.splice(change.index, 0, clone(change.value));
      }
      return true;
    }

    function emit(entry, direction, applied) {
      version++;
      onChange({ command: entry, direction, changes: applied || entry.changes });
    }

    // A later set on the same (target, path) keeps the first before and the last after.
    function merge(entry, changes) {
      const structural = entry.changes.some((change) => change.op !== "set");
      for (const change of changes) {
        const match = !structural && change.op === "set" && entry.changes.find((item) => item.op === "set" && changeKey(item) === changeKey(change));
        if (match) {
          match.after = clone(change.after);
          if (!match.had && match.created < 0 && change.created >= 0) match.created = change.created;
        } else entry.changes.push(change);
      }
    }

    function apply(command) {
      const value = project();
      const entry = normalize(command);
      if (!value || !entry) return false;
      // In order, so a change can build on an earlier one of the same command.
      const applied = [];
      for (const change of entry.changes) if (effective(value, change) && forward(value, change)) applied.push(change);
      if (!applied.length) return false;
      entry.changes = applied;
      redoStack = [];
      const top = undoStack[undoStack.length - 1];
      if (gesture && gesture.entry && top === gesture.entry) {
        merge(top, applied);
        emit(top, "do", applied);
        return true;
      }
      if (!gesture && entry.coalesce && top && top.coalesce === entry.coalesce && top.open) {
        merge(top, applied);
        emit(top, "do", applied);
        return true;
      }
      if (gesture) {
        if (gesture.label) entry.label = gesture.label;
        gesture.entry = entry;
      }
      entry.open = !gesture && !!entry.coalesce;
      for (const previous of undoStack) previous.open = false;
      undoStack.push(entry);
      if (undoStack.length > limit) undoStack.splice(0, undoStack.length - limit);
      emit(entry, "do", applied);
      return true;
    }

    function begin(label) {
      if (depth++ === 0) gesture = { label: typeof label === "string" ? label : "", entry: null };
    }

    function end() {
      if (depth === 0) return;
      if (--depth === 0) gesture = null;
    }

    function step(from, to, direction) {
      gesture = null; depth = 0;
      for (const previous of undoStack) previous.open = false;
      while (from.length) {
        const entry = from.pop();
        const value = project();
        const list = direction === "undo" ? entry.changes.slice().reverse() : entry.changes;
        let any = false;
        for (const change of list) {
          if (direction === "undo" ? backward(value, change) : forward(value, change)) any = true;
        }
        if (!any) continue;   // inert entry: its targets are gone
        to.push(entry);
        emit(entry, direction);
        return true;
      }
      return false;
    }

    function editedEvents() {
      const value = project();
      if (editedCache && editedKey && editedKey.version === version && editedKey.project === value) return editedCache;
      const result = new Set(), editor = editorOf(value, false);
      if (editor) {
        const index = new Map();
        for (const track of value.tracks) for (const event of track.events || []) if (event) index.set(event.id, { track, event });
        for (const id of Object.keys(editor.originals)) {
          const found = index.get(id);
          if (!found) continue;
          const original = editor.originals[id];
          if (original === null || stable(compareView(found.track, found.event)) !== stable(compareView(found.track, original))) result.add(id);
        }
      }
      editedCache = result;
      editedKey = { version, project: value };
      return result;
    }

    const label = (entry) => entry ? entry.label : null;
    return {
      apply, begin, end,
      undo: () => step(undoStack, redoStack, "undo"),
      redo: () => step(redoStack, undoStack, "redo"),
      canUndo: () => undoStack.length > 0,
      canRedo: () => redoStack.length > 0,
      peekUndo: () => undoStack.length ? { label: label(undoStack[undoStack.length - 1]), detail: undoStack[undoStack.length - 1].detail } : null,
      peekRedo: () => redoStack.length ? { label: label(redoStack[redoStack.length - 1]), detail: redoStack[redoStack.length - 1].detail } : null,
      size: () => ({ undo: undoStack.length, redo: redoStack.length }),
      clear() { undoStack = []; redoStack = []; gesture = null; depth = 0; version++; },
      // For writes made outside history (a reload that carries edits): drops cached "edited" results.
      invalidate() { version++; },
      get version() { return version; },
      get gestureActive() { return depth > 0; },
      originals: {
        get(id) { const editor = editorOf(project(), false); return editor && own(editor.originals, id) ? editor.originals[id] : undefined; },
        ensure(id) { return originalsEnsure(id); },
      },
      editedEvents,
    };
  }

  global.MVStudioEditHistory = Object.freeze({ create, stable, clone, editedView, sameTarget });
})(typeof window !== "undefined" ? window : globalThis);
