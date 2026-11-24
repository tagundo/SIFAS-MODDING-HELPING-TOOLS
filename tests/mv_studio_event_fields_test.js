/* Inspector value controls (mv-studio-event-fields.js) on their own: the descriptor
   table against the controls it builds, the HDR colour mapping, 0/1 integers, observed
   options, data-mv-field on writable inputs only, the collapsed native data, and the
   gesture calls of a slider and a colour swatch over a real MVStudioEditHistory. The
   page host (gesture ownership, undo buttons) is covered by mv_studio_fields_browser.js. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const statics = path.resolve(__dirname, '../webtools/web/static');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setContent('<!doctype html><meta charset="utf-8"><div id="box"></div>');
    for (const script of ['viewer-motion-timeline.js', 'mv-studio-timeline-tabs.js', 'mv-studio-edit-history.js', 'mv-studio-event-fields.js']) {
      await page.addScriptTag({ path: path.join(statics, script) });
    }
    const result = await page.evaluate(() => {
      const F = window.MVStudioEventFields;
      const out = {};
      out.registered = window.MVStudioPlugins.map((plugin) => [plugin.id, plugin.order]);
      // HDR colour: {2,1,.5} shows #ff8040 at ×2; a pick keeps ×2.
      out.parts = F.colorParts({ r: 2, g: 1, b: .5, a: 1 });
      out.pick = F.pickColor({ r: 2, g: 1, b: .5, a: 1 }, '#00ff00', 2);
      out.back = F.colorParts(F.pickColor({ r: 0, g: 0, b: 0, a: .25 }, '#ff8040', 2));
      out.scaled = F.scaleColor({ r: 2, g: 1, b: .5, a: .5 }, 3);
      out.ldr = F.colorParts({ r: .5, g: .25, b: 0, a: 1 });

      const make = (tag, label, attrs = {}) => {
        const element = document.createElement(tag);
        if (label != null) element.textContent = label;
        for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
        return element;
      };
      const ko = { 'Tint colour': '틴트 색', 'Light texture': '조명 텍스처', 'Light texture {n}': '조명 텍스처 {n}',
        'Native data (read only)': '원본 데이터 (읽기 전용)', 'Member {n}': '멤버 {n}' };
      const t = (label) => ko[label] || label;
      const project = { version: 1, name: 'Fields', duration: 20, performers: [{ id: 'm1', position: 1, label: '아유무' }, { id: 'm3', position: 3 }],
        tracks: [
          { id: 'coloring', kind: 'stage', events: [
            { id: 'coloring:0', start: 0, duration: 2, label: 'C0', editableValues: ['tintColor', 'textureIndex', 'speed'],
              values: { asset: 'cab:1', playableClass: 'LiveColoringClip', shift: 3, tintColor: { r: 2, g: 1, b: .5, a: 1 }, speed: .5, textureIndex: 0,
                mixIn: [{ time: 0, value: 0 }] } },
            { id: 'coloring:1', start: 2, duration: 2, label: 'C1', editableValues: ['textureIndex'],
              values: { asset: 'cab:2', playableClass: 'LiveColoringClip', shift: 0, tintColor: { r: 0, g: 0, b: 0, a: 0 }, speed: 0, textureIndex: 2 } }] },
          { id: 'coloring-b', kind: 'stage', events: [
            { id: 'coloring-b:0', start: 0, duration: 2, label: 'B0', editableValues: ['textureIndex'],
              values: { asset: 'cab:3', playableClass: 'LiveColoringClip', shift: 0, tintColor: { r: 0, g: 0, b: 0, a: 0 }, speed: 0, textureIndex: 5 } }] },
          { id: 'bloom', kind: 'bloom', events: [
            { id: 'bloom:0', start: 0, duration: 2, label: 'Bloom', editableValues: ['antiFlicker', 'softKnee'],
              values: { asset: 'cab:4', playableClass: 'LiveBloomClip', intensity: .3, threshold: 1, softKnee: .3, radius: 4, antiFlicker: 0 } }] },
          { id: 'gaze', kind: 'gaze', events: [
            { id: 'gaze:0', start: 0, duration: 2, label: 'G', editableValues: ['target'],
              values: { asset: 'cab:5', playableClass: 'MemberGazeClip', target: 34, weightForDirection: 1, splitScreenSetting: { UseSetting: 0 } } }] },
          { id: 'rim', kind: 'lighting', events: [
            { id: 'rim:0', start: 0, duration: 2, label: 'R', editableValues: ['direction', 'colorSpecifiedType'],
              values: { asset: 'cab:6', playableClass: 'LiveRimlightClip', colorSpecifiedType: 0, color: { r: 1, g: 1, b: 1, a: 0 },
                memberPosition: 1, intensity: 1, sharpness: 8, direction: { x: -24, y: 12, z: 0 } } }] },
          { id: 'eye', kind: 'eyes', events: [
            { id: 'eye:0', start: 0, duration: 2, label: 'E', editableValues: ['index'],
              values: { asset: 'cab:7', playableClass: 'MemberEyeClip', index: 7, weight: 1 } }] },
          { id: 'fx', kind: 'effects', events: [
            { id: 'fx:0', start: 0, duration: 2, label: 'F', editableValues: ['offset', 'weight'],
              values: { asset: 'cab:8', playableClass: 'CustomControlClip', prefabGameObject: { m_FileID: 0, m_PathID: '5' },
                particleRandomSeed: 7, overwriteRandomSeed: 0, weight: 1, offset: { x: 0, y: 0, z: 0 } } }] },
          { id: 'prop', kind: 'lighting', events: [
            { id: 'prop:0', start: 0, duration: 2, label: 'P', editableValues: ['color'],
              values: { asset: 'cab:9', playableClass: 'LivePropAmbientClip', color: { r: 2, g: 1, b: .5, a: 1 },
                tintColor: { r: 1, g: 1, b: 1, a: 1 }, colorSpecifiedType: 0, memberPosition: 1 } }] },
        ] };
      const history = MVStudioEditHistory.create({ getProject: () => project });
      const ctx = {
        project: () => project, history, t, make,
        format: (label, values) => t(label).replace(/\{(\w+)\}/g, (match, key) => key in values ? String(values[key]) : match),
      };
      const find = (id) => { for (const track of project.tracks) for (const event of track.events) if (event.id === id) return { track, event }; };
      const opened = [];
      function control(id, key) {
        const { track, event } = find(id);
        let token = null;
        const info = { track, event, key, path: key, value: event.values[key], writable: event.editableValues.includes(key),
          original: undefined,
          set: (next) => history.apply({ label: 'Edit value', detail: key, changes: [{ target: { kind: 'event', track: track.id, event: id }, path: ['values', key], after: next }] }),
          gesture: { begin: () => { if (token && history.gestureToken === token) return; opened.push(key); token = history.begin('Edit value'); },
            end: () => { if (token) history.end(token); } } };
        const element = F.plugin.valueControl(ctx, info);
        if (element) document.getElementById('box').append(element);
        return element;
      }
      const fields = (element) => element ? [...element.querySelectorAll('[data-mv-field]')].map((item) => item.dataset.mvField) : null;

      // Identity keys are hidden from the list and shown once in the footer.
      out.hidden = ['asset', 'playableClass', 'mixIn'].map((key) => control('coloring:0', key));
      out.pointer = control('fx:0', 'prefabGameObject');
      out.seed = control('fx:0', 'particleRandomSeed');
      const footer = F.plugin.eventFooter(ctx, find('coloring:0'));
      out.footer = { open: footer.open, summary: footer.querySelector('summary').textContent, tag: footer.tagName, cls: footer.className,
        keys: [...footer.querySelectorAll('[data-mv-native]')].map((item) => item.dataset.mvNative),
        fields: footer.querySelectorAll('[data-mv-field]').length };
      out.noFooter = F.plugin.eventFooter(ctx, { track: {}, event: { values: { fov: 30 } } }) === undefined;
      out.unknown = control('gaze:0', 'splitScreenSetting');
      out.legacyTiming = control('bloom:0', 'blendIn');
      out.noClass = F.plugin.valueControl(ctx, { track: {}, event: { values: { fov: 30 } }, key: 'fov', path: 'fov', value: 30, writable: true });

      // Colour: writable, swatch + intensity + channels, a pick keeps the intensity.
      const tint = control('coloring:0', 'tintColor');
      const swatch = tint.querySelector('input[type=color]');
      out.tint = { fields: fields(tint), swatch: swatch.value, intensity: tint.querySelector('.mv-color-intensity').value,
        label: tint.querySelector('.mv-value-label').textContent, wide: tint.classList.contains('mv-value-wide') };
      swatch.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, isPrimary: true }));
      swatch.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      for (const hex of ['#00ff00', '#00ff80', '#0000ff']) {
        swatch.value = hex;
        swatch.dispatchEvent(new Event('input', { bubbles: true }));
      }
      swatch.dispatchEvent(new Event('change', { bubbles: true }));
      out.picked = { value: find('coloring:0').event.values.tintColor, undo: history.size().undo, open: history.gestureActive,
        r: tint.querySelector('[data-mv-field="tintColor.r"]').value, b: tint.querySelector('[data-mv-field="tintColor.b"]').value };
      // A keyboard-opened picker (click only) is one step too.
      swatch.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      swatch.value = '#ff0000';
      swatch.dispatchEvent(new Event('input', { bubbles: true }));
      swatch.dispatchEvent(new Event('change', { bubbles: true }));
      out.keyboardPick = { value: find('coloring:0').event.values.tintColor, undo: history.size().undo, open: history.gestureActive };
      const intensity = tint.querySelector('.mv-color-intensity');
      intensity.value = '4';
      intensity.dispatchEvent(new Event('change', { bubbles: true }));
      out.brighter = { value: find('coloring:0').event.values.tintColor, undo: history.size().undo, swatch: swatch.value };
      // The next picker session picks at the new intensity.
      swatch.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      swatch.value = '#00ff00';
      swatch.dispatchEvent(new Event('input', { bubbles: true }));
      swatch.dispatchEvent(new Event('change', { bubbles: true }));
      out.repicked = { value: find('coloring:0').event.values.tintColor, undo: history.size().undo };
      history.undo();
      out.undone = find('coloring:0').event.values.tintColor;

      // The intensity is k = max(1, r, g, b): an entry below 1 clamps to 1 once and never compounds.
      const prop = control('prop:0', 'color');
      const propIntensity = prop.querySelector('.mv-color-intensity');
      const propBefore = history.size().undo;
      out.propIntensity = { min: propIntensity.min, shown: propIntensity.value, entries: [] };
      for (const entry of ['0.5', '0.5', '1', '0']) {
        propIntensity.value = entry;
        propIntensity.dispatchEvent(new Event('change', { bubbles: true }));
        out.propIntensity.entries.push({ value: { ...find('prop:0').event.values.color }, shown: propIntensity.value,
          steps: history.size().undo - propBefore, swatch: prop.querySelector('input[type=color]').value });
      }
      // Below 1 is still reachable through the exact values.
      const red = prop.querySelector('[data-mv-field="color.r"]');
      red.value = '0.25';
      red.dispatchEvent(new Event('change', { bubbles: true }));
      out.propExact = { value: { ...find('prop:0').event.values.color }, shown: propIntensity.value, steps: history.size().undo - propBefore };

      // Observed options: this track's values only, labelled; not writable → read only.
      const texture = control('coloring:0', 'textureIndex');
      out.texture = { options: [...texture.querySelectorAll('option')].map((option) => [option.value, option.textContent]), fields: fields(texture) };
      texture.querySelector('select').value = '2';
      texture.querySelector('select').dispatchEvent(new Event('change', { bubbles: true }));
      out.textureValue = find('coloring:0').event.values.textureIndex;
      const shift = control('coloring:0', 'shift');
      out.shift = { fields: fields(shift), text: shift.querySelector('output')?.textContent };

      // 0/1 ints stay ints.
      const flicker = control('bloom:0', 'antiFlicker');
      const box = flicker.querySelector('input[type=checkbox]');
      out.flickerFields = fields(flicker);
      box.click();
      out.flicker = find('bloom:0').event.values.antiFlicker;
      box.click();
      out.flickerOff = find('bloom:0').event.values.antiFlicker;

      // Slider: a drag (pointerdown, inputs, change, pointerup, click) is one gesture and one step.
      const knee = control('bloom:0', 'softKnee');
      const range = knee.querySelector('input[type=range]');
      const before = history.size().undo;
      opened.length = 0;
      range.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, isPrimary: true }));
      for (const value of ['.4', '.5', '.62']) { range.value = value; range.dispatchEvent(new Event('input', { bubbles: true })); }
      range.dispatchEvent(new Event('change', { bubbles: true }));
      range.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, isPrimary: true }));
      range.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      out.slider = { steps: history.size().undo - before, value: find('bloom:0').event.values.softKnee, open: history.gestureActive,
        begun: opened.slice(), box: knee.querySelector('[data-mv-field=softKnee]').value, fields: fields(knee),
        range: range.dataset.mvField === undefined };
      // The number box beside it is one step per change.
      const number = knee.querySelector('[data-mv-field=softKnee]');
      number.value = '0.8';
      number.dispatchEvent(new Event('change', { bubbles: true }));
      out.sliderBox = { steps: history.size().undo - before, value: find('bloom:0').event.values.softKnee, range: range.value };

      // Gaze targets: present members, camera, audience, then the clip's own value.
      const gaze = control('gaze:0', 'target');
      out.gaze = [...gaze.querySelectorAll('option')].map((option) => [Number(option.value), option.textContent]);
      out.gazeWeight = fields(control('gaze:0', 'weightForDirection'));

      // Vector X/Y/Z, enum colour source, member position read only.
      const direction = control('rim:0', 'direction');
      out.direction = fields(direction);
      const y = direction.querySelector('[data-mv-field="direction.y"]');
      y.value = '-3';
      y.dispatchEvent(new Event('change', { bubbles: true }));
      out.directionValue = find('rim:0').event.values.direction;
      const source = control('rim:0', 'colorSpecifiedType');
      out.source = [...source.querySelectorAll('option')].map((option) => option.textContent);
      const member = control('rim:0', 'memberPosition');
      out.member = { fields: fields(member), text: member.querySelector('output').textContent };
      const rimColour = control('rim:0', 'color');
      out.rimColour = { fields: fields(rimColour), text: rimColour.querySelector('output').textContent };

      // Facial index: live ids, plus the clip's own unplayed value.
      const eye = control('eye:0', 'index');
      const eyeOptions = [...eye.querySelectorAll('option')].map((option) => [Number(option.value), option.textContent]);
      out.eye = { count: eyeOptions.length, first: eyeOptions[0], last: eyeOptions.at(-1), selected: eye.querySelector('select').value };

      // Not previewed: badge.
      const offset = control('fx:0', 'offset');
      out.offset = { fields: fields(offset), badge: offset.querySelector('.mv-field-badge')?.textContent,
        badgeTitle: offset.querySelector('.mv-field-badge')?.title };
      out.weightBadge = !!control('fx:0', 'weight').querySelector('.mv-field-badge');
      out.tintBadge = !!tint.querySelector('.mv-field-badge');
      return out;
    });

    assert.deepEqual(errors, []);
    assert.deepEqual(result.registered, [['event-fields', 10]]);
    assert.deepEqual(result.parts, { hex: '#ff8040', k: 2 });
    assert.deepEqual(result.pick, { r: 0, g: 2, b: 0, a: 1 }, 'picking #00ff00 keeps ×2');
    assert.deepEqual(result.back, { hex: '#ff8040', k: 2 });
    assert.deepEqual(result.scaled, { r: 3, g: 1.5, b: .75, a: .5 });
    assert.deepEqual(result.ldr, { hex: '#804000', k: 1 });

    assert.deepEqual(result.hidden, [null, null, null], 'identity keys are hidden from the list');
    assert.equal(result.pointer, null, 'PPtr dicts are identity data');
    assert.equal(result.seed, null);
    assert.deepEqual(result.footer, { open: false, summary: '원본 데이터 (읽기 전용)', tag: 'DETAILS', cls: 'mv-native-fields',
      keys: ['asset', 'playableClass', 'mixIn'], fields: 0 });
    assert.equal(result.noFooter, true, 'no identity data, no footer');
    assert.equal(result.unknown, undefined, 'a key without a descriptor keeps the built-in field');
    assert.equal(result.legacyTiming, undefined, 'timing stays with the host');
    assert.equal(result.noClass, undefined, 'events without a playable class keep the built-in fields');

    assert.deepEqual(result.tint.fields, ['tintColor', 'tintColor.intensity', 'tintColor.r', 'tintColor.g', 'tintColor.b', 'tintColor.a']);
    assert.equal(result.tint.swatch, '#ff8040');
    assert.equal(result.tint.intensity, '2');
    assert.equal(result.tint.label, '틴트 색');
    assert(result.tint.wide);
    assert.deepEqual(result.picked.value, { r: 0, g: 0, b: 2, a: 1 }, 'the last pick at ×2');
    assert.equal(result.picked.undo, 1, 'a picker session is one undo step');
    assert.equal(result.picked.open, false, 'change ends the gesture');
    assert.deepEqual([result.picked.r, result.picked.b], ['0', '2']);
    assert.deepEqual(result.keyboardPick, { value: { r: 2, g: 0, b: 0, a: 1 }, undo: 2, open: false });
    assert.deepEqual(result.brighter, { value: { r: 4, g: 0, b: 0, a: 1 }, undo: 3, swatch: '#ff0000' }, 'the intensity box scales the hue');
    assert.deepEqual(result.repicked, { value: { r: 0, g: 4, b: 0, a: 1 }, undo: 4 }, 'a later pick keeps the edited intensity');
    assert.deepEqual(result.undone, { r: 4, g: 0, b: 0, a: 1 });
    assert.deepEqual([result.propIntensity.min, result.propIntensity.shown], ['1', '2']);
    assert.deepEqual(result.propIntensity.entries, [
      { value: { r: 1, g: .5, b: .25, a: 1 }, shown: '1', steps: 1, swatch: '#ff8040' },
      { value: { r: 1, g: .5, b: .25, a: 1 }, shown: '1', steps: 1, swatch: '#ff8040' },
      { value: { r: 1, g: .5, b: .25, a: 1 }, shown: '1', steps: 1, swatch: '#ff8040' },
      { value: { r: 1, g: .5, b: .25, a: 1 }, shown: '1', steps: 1, swatch: '#ff8040' },
    ], 'an intensity below 1 clamps to 1 once: no compounding, and the box shows the stored intensity');
    assert.deepEqual(result.propExact, { value: { r: .25, g: .5, b: .25, a: 1 }, shown: '1', steps: 2 },
      'channels below 1 stay editable in the exact values');

    assert.deepEqual(result.texture.options, [['0', '조명 텍스처 0'], ['2', '조명 텍스처 2']], 'observed on this track only');
    assert.deepEqual(result.texture.fields, ['textureIndex']);
    assert.equal(result.textureValue, 2);
    assert.deepEqual(result.shift, { fields: [], text: '3' }, 'a value outside editableValues is read only, with no data-mv-field');

    assert.deepEqual(result.flickerFields, ['antiFlicker']);
    assert.equal(result.flicker, 1);
    assert.equal(result.flickerOff, 0);
    assert.equal(Number.isInteger(result.flicker), true);

    assert.equal(result.slider.steps, 1, 'a slider drag is one undo step');
    assert.equal(result.slider.value, .62);
    assert.equal(result.slider.open, false);
    assert.deepEqual(result.slider.begun, ['softKnee'], 'the slider begins once, on pointerdown, never on click');
    assert.equal(result.slider.box, '0.62');
    assert.deepEqual(result.slider.fields, ['softKnee'], 'the number box carries data-mv-field, the range does not');
    assert(result.slider.range);
    assert.deepEqual(result.sliderBox, { steps: 2, value: .8, range: '0.8' });

    assert.deepEqual(result.gaze, [[1, '멤버 1 · 아유무'], [3, '멤버 3'], [21, 'Camera'], [22, 'Audience'], [34, 'Fixed eye direction 4']]);
    assert.deepEqual(result.gazeWeight, [], 'weightForDirection is not in editableValues here: read only');
    assert.deepEqual(result.direction, ['direction.x', 'direction.y', 'direction.z']);
    assert.deepEqual(result.directionValue, { x: -24, y: -3, z: 0 });
    assert.deepEqual(result.source, ['Custom colour', 'Member colour', 'Original member colour']);
    assert.deepEqual(result.member, { fields: [], text: '멤버 1 · 아유무' });
    assert.deepEqual(result.rimColour.fields, [], 'a colour outside editableValues is read only');
    assert.match(result.rimColour.text, /R 1 · G 1 · B 1 · A 0/);
    assert.equal(result.eye.count, 24, '23 live eye ids and the clip\'s own unplayed value');
    assert.deepEqual(result.eye.first, [1, '1']);
    assert.deepEqual(result.eye.last, [7, '7 (not played in MVs)']);
    assert.equal(result.eye.selected, '7');
    assert.deepEqual(result.offset.fields, ['offset.x', 'offset.y', 'offset.z']);
    assert.equal(result.offset.badge, 'Not shown in the preview');
    assert.match(result.offset.badgeTitle, /exported to the game/);
    assert(result.weightBadge);
    assert(!result.tintBadge);
    console.log('MV Studio event fields: descriptors, HDR colour, 0/1 ints, observed options, data-mv-field, native data, gestures passed');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
