/* MV Studio timeline tabs (mv-studio-timeline-tabs.js): category counts of the real
   12035 timeline structure, classes the seven cached MVs do not use, the member slot
   and member filter, the lane plan per tab (groups, Edit sections, filters, plugin
   lanes) and the roving keyboard model of the tablist. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-timeline-tabs.js');
const Tabs = globalThis.MVStudioTimelineTabs;

// tests/fixtures/mv_studio_tracks_12035.json keeps a track-level editableValues for its events.
function fixture() {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'mv_studio_tracks_12035.json'), 'utf8'));
  for (const track of data.tracks) {
    for (const event of track.events) if (!event.editableValues && track.editableValues) event.editableValues = track.editableValues.slice();
    delete track.editableValues;
  }
  return data;
}

function counts12035() {
  const { tracks } = fixture();
  const census = Tabs.census(tracks);
  const summary = Object.fromEntries(Object.entries(census).map(([id, value]) => [id, `${value.tracks}/${value.events}`]));
  assert.deepEqual(summary, {
    edit: '0/0', all: '67/1117', dance: '2/2', camera: '2/79', expression: '3/96', mouth: '1/272', lighting: '8/293',
    stage: '13/221', effects: '8/35', props: '0/0', post: '4/114', crowd: '1/5', sound: '0/0', other: '0/0', group: '25/0',
  });
  assert.deepEqual(Tabs.visibleTabs(census),
    ['edit', 'all', 'dance', 'camera', 'expression', 'mouth', 'lighting', 'stage', 'effects', 'post', 'crowd'],
    'empty categories are hidden; Edit and All always show');
  // Flares are screen effects with bloom; prop lights stay in Lighting; DOF is per-shot lens (Camera).
  const byLabel = Object.fromEntries(tracks.map((track) => [track.label, Tabs.tabOf(track)]));
  assert.equal(byLabel['StageEffect/Expert/Post/Flare1'], 'post');
  assert.equal(byLabel['StageEffect/Expert/Post/Bloom'], 'post');
  assert.equal(byLabel['StageEffect/Expert/Post/DOF'], 'camera');
  assert.equal(byLabel['PropEffect/Expert/PropAmbient/Live Prop Ambient Track'], 'lighting');
  assert.equal(byLabel['StageEffect/Expert/Animation/litB_All'], 'effects');
  assert.equal(byLabel['StageEffect/Expert/Display/main_01_act'], 'stage');
  assert.equal(byLabel['MemberScale/Member1'], 'dance');
  assert.deepEqual(tracks.filter((track) => Tabs.memberSlot(track) === 1).map((track) => track.label), [
    'MemberMotion/Member1', 'MemberScale/Member1', 'Member1/LipSync', 'Member1/Eye', 'Member1/Gaze', 'Member1/Cheek',
    'MemberEffect/Expert/MemberAmbient/Member1 (1)', 'MemberEffect/Expert/MemberRimlight/Member1 (1)',
    'MemberEffect/Expert/MemberSpotLightShaft/Member1', 'MemberEffect/Expert/MemberSpotLightArea/Member1']);
  assert.equal(Tabs.memberSlot(tracks.find((track) => track.label === 'Member1')), null, 'a group is not member-bound');
}

function synthetic() {
  const track = (nativeClass, kind, binding) => ({ id: nativeClass + kind, nativeClass, kind, binding, events: [] });
  const cases = [
    [track('LiveSplitScreenTrack', 'split'), 'camera'],
    [track('LiveCameraOffsetTrack', 'camera'), 'camera'],
    [track('LiveCameraCutMarkerTrack', 'camera'), 'camera'],
    [track('LiveMemberCullerTrack', 'dance'), 'dance'],
    [track('LiveMemberShadowTrack', 'effects', '/EntryPoint/Live/Members/Member2'), 'dance'],
    [track('LiveMemberIKTrack', 'other'), 'dance'],
    [track('LiveDisplayCameraTrack', 'display'), 'stage'],
    [track('LivePropColoringTrack', 'display'), 'props'],
    [track('LiveBaseLightTrack', 'lighting'), 'lighting'],
    [track('LiveStageEmissiveTrack', 'lighting'), 'lighting'],
    [track('LiveStageSingleAmbientTrack', 'lighting'), 'lighting'],
    [track('ControlTrack', 'effects'), 'effects'],
    [track('AnimationTrack', 'effects', '/EntryPoint/Live/Members/ske_cos_01/Member3/Model/root/hip/hand_R/chp0101'), 'props'],
    [track('ActivationTrack', 'stage', '/EntryPoint/Live/Members/ske_cos_01/Member3/Model/root/chp0101'), 'props'],
    [track('AnimationTrack', 'camera', '/EntryPoint/Live/Cameras/SubCamera2'), 'camera'],
    [track('AnimationTrack', 'stage', '/EntryPoint/Live/Stages/MainStage/root/obj'), 'stage'],
    [track('AnimationTrack', 'effects', '/EntryPoint/Live/Stages/MainStage/EFFECT/fx'), 'effects'],
    [track('AudioTrack', 'sound'), 'sound'],
    [track('NaviVoiceTrack', 'sound'), 'sound'],
    [track('SomeFutureTrack', 'other'), 'other'],
    [track('SomeFutureTrack', 'bloom'), 'post'],
    [track('GroupTrack', 'group'), 'group'],
  ];
  for (const [item, expected] of cases) assert.equal(Tabs.tabOf(item), expected, `${item.nativeClass} ${item.binding || ''}`);
  // User and mod tracks without a native class: by kind.
  const kinds = { camera: 'camera', split: 'camera', dof: 'camera', dance: 'dance', eyes: 'expression', gaze: 'expression',
    cheek: 'expression', mouth: 'mouth', lighting: 'lighting', bloom: 'post', display: 'stage', stage: 'stage', effects: 'effects',
    props: 'props', crowd: 'crowd', sound: 'sound', mystery: 'other', group: 'group' };
  for (const [kind, expected] of Object.entries(kinds)) assert.equal(Tabs.tabOf({ id: kind, kind, events: [] }), expected, kind);
  assert.equal(Tabs.memberSlot(cases[12][0]), 3, 'a prop on a performer bone belongs to that member');
  assert.equal(Tabs.memberSlot({ kind: 'mouth', label: 'Member2/LipSync', events: [] }), 2, 'label fallback without a binding');
  assert.equal(Tabs.memberSlot({ kind: 'mouth', label: 'Member2/LipSync', binding: '/EntryPoint/Live/Stages/x', events: [] }), null);
}

function keyboard() {
  const ids = ['edit', 'all', 'camera', 'mouth'];
  assert.equal(Tabs.keyTarget(ids, 'all', 'ArrowRight'), 'camera');
  assert.equal(Tabs.keyTarget(ids, 'mouth', 'ArrowRight'), 'edit', '→ wraps to the first tab');
  assert.equal(Tabs.keyTarget(ids, 'edit', 'ArrowLeft'), 'mouth', '← wraps to the last tab');
  assert.equal(Tabs.keyTarget(ids, 'camera', 'Home'), 'edit');
  assert.equal(Tabs.keyTarget(ids, 'camera', 'End'), 'mouth');
  assert.equal(Tabs.keyTarget(ids, 'camera', 'Enter'), null, 'Enter/Space are the buttons\' own activation');
}

function plans() {
  const { tracks } = fixture();
  const rows = (plan) => plan.rows.map((row) => row.type === 'track' || row.type === 'group' ? `${row.type}:${row.track.label}` : row.type === 'extra' ? `extra:${row.lane.id}` : row.type);
  const camera = Tabs.plan(tracks, { tab: 'camera' });
  assert.deepEqual(rows(camera), ['track:CameraMotion/Camera1', 'track:StageEffect/Expert/Post/DOF']);
  assert.equal(camera.memberTracks, false, 'no member chips on the Camera tab of 12035');
  const all = Tabs.plan(tracks, { tab: 'all' });
  assert.equal(all.rows.filter((row) => row.type === 'group').length, 25, 'GroupTracks are header rows in All');
  assert.equal(all.tracks.length, 42);
  assert.equal(Tabs.plan(tracks, { tab: 'mouth' }).rows.some((row) => row.type === 'group'), false, 'other tabs hide groups');

  // Edit tab without edits: hint, separator, then the value-editable tracks.
  const edit = Tabs.plan(tracks, { tab: 'edit' });
  assert.equal(edit.rows[0].type, 'hint');
  assert.equal(edit.rows[1].type, 'separator');
  const editable = tracks.filter(Tabs.valueEditable);
  assert.deepEqual(edit.tracks, editable);
  assert(!editable.some((track) => track.label === 'MemberMotion/Member1'), 'timing-only tracks are not listed');
  // With an edited lip-sync clip and a plugin lane: edited tracks, plugin lanes, separator, the rest.
  const lip = tracks.find((track) => track.label === 'Member1/LipSync');
  const rig = { id: 'camera-rigs', after: 't01', label: 'Camera rigs (editor)', render() {} };
  const edited = Tabs.plan(tracks, { tab: 'edit', edited: new Set([lip.events[3].id]), extra: [rig] });
  assert.deepEqual(rows(edited).slice(0, 3), ['track:Member1/LipSync', 'extra:camera-rigs', 'separator']);
  assert(!edited.rows.slice(3).some((row) => row.track === lip), 'an edited track is listed once');
  // A plugin lane that is always there but holds nothing keeps the hint; plugin edits drop it.
  assert.deepEqual(rows(Tabs.plan(tracks, { tab: 'edit', extra: [rig] })).slice(0, 3), ['extra:camera-rigs', 'hint', 'separator']);
  assert.deepEqual(rows(Tabs.plan(tracks, { tab: 'edit', extra: [rig], pluginEdits: 2 })).slice(0, 2), ['extra:camera-rigs', 'separator']);
  assert.deepEqual(rows(Tabs.plan(tracks, { tab: 'edit', pluginEdits: 0 })).slice(0, 2), ['hint', 'separator']);

  // Member filter, name search, editable-only and native group combine with the tab.
  const solo = Tabs.plan(tracks, { tab: 'lighting', member: 1 });
  assert(solo.memberTracks);
  assert.deepEqual(solo.tracks.map((track) => track.label), ['MemberEffect/Expert/MemberAmbient/Member1 (1)',
    'MemberEffect/Expert/MemberRimlight/Member1 (1)', 'MemberEffect/Expert/MemberSpotLightShaft/Member1', 'MemberEffect/Expert/MemberSpotLightArea/Member1']);
  assert.deepEqual(Tabs.plan(tracks, { tab: 'lighting', member: 2 }).tracks, []);
  assert.equal(Tabs.plan(tracks, { tab: 'camera', member: 1 }).member, null, 'a tab without member tracks ignores the member filter');
  const search = Tabs.plan(tracks, { tab: 'all', search: 'ＬＥＤ_panel' });
  assert.deepEqual(search.tracks.map((track) => track.label.split('/').pop()), ['LED_panel_01', 'LED_panel_02', 'LED_panel_03', 'LED_panel_04']);
  assert.deepEqual(rows(search).filter((row) => row.startsWith('group:')),
    ['group:StageEffect', 'group:StageEffect/Expert', 'group:StageEffect/Expert/Coloring'], 'only groups holding a match stay');
  const grouped = Tabs.plan(tracks, { tab: 'stage', group: 'StageEffect/Expert/Display' });
  assert.deepEqual(grouped.tracks.map((track) => track.label.split('/').pop()), ['main_01_act', 'sub_01_act', 'main_01', 'sub_01']);
  assert(grouped.groups.includes('StageEffect/Expert/Coloring'));
  assert.equal(Tabs.plan(tracks, { tab: 'stage', group: 'Nope' }).group, '', 'an unknown group falls back to all groups');
  const editableOnly = Tabs.plan(tracks, { tab: 'stage', editableOnly: true });
  assert(editableOnly.tracks.every(Tabs.valueEditable));
  assert(editableOnly.tracks.length < Tabs.plan(tracks, { tab: 'stage' }).tracks.length);

  // Plugin lanes: after their track, at the top without one, at the end when the track is hidden.
  const lanes = [{ id: 'a', after: 't01', label: 'A' }, { id: 'b', after: null, label: 'B' }, { id: 'c', after: 't99', label: 'C' }];
  assert.deepEqual(rows(Tabs.plan(tracks, { tab: 'camera', extra: lanes })),
    ['extra:b', 'track:CameraMotion/Camera1', 'extra:a', 'track:StageEffect/Expert/Post/DOF', 'extra:c']);
  assert.deepEqual(rows(Tabs.plan(tracks, { tab: 'camera', extra: lanes, search: 'dof' })), ['track:StageEffect/Expert/Post/DOF']);
}

function members() {
  const project = { performers: [{ position: 2, label: '나카스 카스미', themeColor: [1, .8, 0, 1] }, { position: 1, label: 'Member 1' }],
    tracks: [{ id: 'x', kind: 'mouth', binding: '/EntryPoint/Live/Members/Member3', events: [] }] };
  assert.deepEqual(Tabs.memberChoices(project), [
    { slot: 1, name: '', color: null }, { slot: 2, name: '나카스 카스미', color: [1, .8, 0] }, { slot: 3, name: '', color: null }]);
}

// Tracks whose mute the game sets from a quality flag (LiveQualityOperator.MuteTracks).
function qualityMutes() {
  const { tracks } = fixture();
  const leaf = (label) => tracks.find((track) => track.label === label);
  const driven = tracks.filter(Tabs.qualityMuted).map((track) => track.label);
  // 12035: every direct child of a StageEffect category, and of the MemberEffect and PropEffect categories.
  assert(driven.includes('StageEffect/Expert/Coloring/LED_panel_01'));
  assert(driven.includes('StageEffect/Expert/Flash Light/Live Flash Light Track'), 'spaces are removed from the category');
  assert(driven.includes('MemberEffect/Expert/MemberRimlight/Member1 (1)'));
  assert(!driven.includes('Member1/LipSync') && !driven.includes('CameraMotion/Camera1'), 'other tracks keep their own mute');
  assert(!driven.some((label) => label.split('/').length !== 4), 'only direct children');
  assert(tracks.filter(Tabs.isGroup).every((track) => !Tabs.qualityMuted(track)), 'groups never');
  assert.equal(Tabs.qualityOption(leaf('StageEffect/Expert/Flash Light/Live Flash Light Track')), 'stage_flash_light');
  assert.equal(Tabs.qualityOption(leaf('StageEffect/Expert/Coloring')), 'stage_coloring', 'the category group itself');
  assert.equal(Tabs.qualityOption(leaf('MemberEffect/Expert/MemberRimlight/Member1 (1)')), null, 'member flags are not named');
  assert.equal(Tabs.qualityOption({ label: 'StageEffect/Expert/Coloring/LightShaft/Live Coloring Track', kind: 'display' }), null,
    'a track in a sub-group keeps its own mute (12023)');
  assert.equal(Tabs.qualityOption({ label: 'StageEffect/Expert/Overlay/x', kind: 'effects' }), null, 'an unknown category');
  // Every category of the other quality roots (their names were not read from the client).
  assert.equal(Tabs.qualityMuted({ label: 'PropEffect/Expert/PropAnimation/x', kind: 'props' }), true);
  assert.equal(Tabs.qualityMuted({ label: 'MotionMisc/Expert/SplitScreen/x', kind: 'camera' }), true);
  assert.equal(Tabs.qualityMuted({ label: 'GlobalEffect/Expert/BaseLight/BaseLight', kind: 'lighting' }), true);
  assert.equal(Tabs.qualityMuted({ label: 'MemberEffect/Expert/MemberAmbient/Sub/x', kind: 'lighting' }), false, 'one group deeper');
  assert.equal(Tabs.qualityMuted({ label: 'CameraOffset/Expert/X/x', kind: 'camera' }), false, 'another root');
  assert.deepEqual(Object.keys(Tabs.STAGE_QUALITY).sort(), ['ambient', 'animation', 'audience', 'coloring', 'control', 'display',
    'emissive', 'flashlight', 'overlayeffect', 'post']);
  assert(Object.values(Tabs.STAGE_QUALITY).every((key) => Tabs.QUALITY_LABELS[key]));

  // Badges: the category group and its direct children, except an ActivationTrack (the flag
  // never mutes one: ApplyMuteToTrack skips it when muting).
  const badged = tracks.filter(Tabs.qualityBadge).map((track) => track.label);
  assert(badged.includes('StageEffect/Expert/Coloring') && badged.includes('StageEffect/Expert/Coloring/LED_panel_01'));
  assert(!badged.includes('StageEffect/Expert/Display/main_01_act'), 'an ActivationTrack keeps playing');
  assert(badged.includes('StageEffect/Expert/Display/main_01'));
  assert(!badged.some((label) => !label.startsWith('StageEffect/')), 'StageEffect only');
  assert(!badged.includes('StageEffect/Expert'), 'not the difficulty group');

  // A mute edit lists its track first in the Edit tab, like an edited clip.
  const lips = leaf('Member1/LipSync');
  const plan = Tabs.plan(tracks, { tab: 'edit', editedTracks: new Set([lips.id]) });
  assert.deepEqual(plan.rows.slice(0, 2).map((row) => row.type + ':' + (row.track ? row.track.label : '')), ['track:Member1/LipSync', 'separator:']);
  assert.equal(plan.rows.filter((row) => row.type === 'hint').length, 0, 'no hint once a track is edited');
}

counts12035();
synthetic();
keyboard();
plans();
members();
qualityMutes();
console.log('MV Studio timeline tabs: 12035 counts, synthetic classes, member slots, lane plans per tab and filter, roving keys, quality-set mutes.');
