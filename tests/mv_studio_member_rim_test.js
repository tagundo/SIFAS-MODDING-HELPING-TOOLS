"use strict";
/* Member rim mixing (MVStudioLighting.member) against the original client.

   LiveRimlightMixer (client IL2CPP): PreProcess zeroes colour, intensity,
   sharpness and direction; Process adds CalculateMemberColor(clip) * weight,
   clip.intensity * weight, clip.sharpness * weight and clip.direction * weight;
   PostProcess applies them through LiveCoreMemberRimlight when an input ran
   (ApplyRimlightColor: base * colour unless the base colour is invalid;
   ApplyIntensity: base + intensity; ApplySharpness: _RimglightPower =
   base + 1 + sharpness; ApplyDirection: base.xyz + direction) and otherwise
   only ApplyIntensity(0). The expected values are the AS/Member material
   values of the 12035 Max 3D game dump (Special Stage, Member1), whose song
   has no LiveBaseLightTrack, at director 14.946 and 72.398 and at 45.261,
   where the material still holds the previous game frame's evaluation
   (the 42.6 s clip; deltaTime 0.146 s, the next clip starts at 45.117 s). */

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-lighting.js");

const { sample } = globalThis.MVStudioLighting;
const clip = (start, duration, intensity, sharpness, color, direction, blend = {}) => ({ start, duration, values: {
  playableClass: "LiveRimlightClip", colorSpecifiedType: 0, memberPosition: 1, intensity, sharpness,
  color: { r: color[0], g: color[1], b: color[2], a: color[3] }, direction: { x: direction[0], y: direction[1], z: direction[2] },
  easeIn: 0, easeOut: 0, blendIn: -1, blendOut: -1, ...blend,
} });
// LiveRimlightTrack clips of the original 12035 timeline (Member1).
const project = { quality: { values: { member_rim_light: true, base_light: true } }, tracks: [{
  nativeClass: "LiveRimlightTrack", binding: "/EntryPoint/Live/Members/Member1", events: [
    clip(13.717, 0.883, 1.2, 5, [0.4, 0.5394615530967712, 0.8, 1], [-5, 0.5, 0], { blendOut: 0.36666666666666714 }),
    clip(14.233, 1.433, 0.75, 12, [0.4313725233078003, 0.44977471232414246, 1, 1], [-9, 6, 0], { blendIn: 0.36666666666666714 }),
    clip(42.6, 2.517, 0.5, 12, [0.44811320304870605, 0.6331031918525696, 1, 1], [1.600000023841858, 1.5, 0]),
    clip(45.117, 1.95, 0.75, 20, [0.30000001192092896, 0.5333334803581238, 1, 1], [-0.699999988079071, 0.5, 0], { blendOut: 0.6 }),
    clip(71.0, 2.9, 0.699999988079071, 20, [0.47843137383461, 0.5882353186607361, 0.800000011920929, 1], [-0.699999988079071, 0.5, 0]),
  ] }] };

const game = [
  [14.946, { intensity: 0.75, power: 13, color: [0.4313725, 0.4497747, 1, 1], direction: [-9, 6, 0, 0] }],
  [45.261 - 0.146, { intensity: 0.5, power: 13, color: [0.4481132, 0.6331032, 1, 1], direction: [1.6, 1.5, 0, 0] }],
  [72.398, { intensity: 0.7, power: 21, color: [0.4784314, 0.5882353, 0.8, 1], direction: [-0.7, 0.5, 0, 0] }],
];
for (const [time, expected] of game) {
  const rim = sample(project, time).member(1).rim;
  for (const key of ["intensity", "power"]) assert(Math.abs(rim[key] - expected[key]) < 1e-6, `${key} at ${time}: ${rim[key]}`);
  for (const key of ["color", "direction"]) {
    rim[key].forEach((value, index) => assert(Math.abs(value - expected[key][index]) < 1e-6, `${key} at ${time}: ${rim[key]}`));
  }
}
// Between clips no input runs: PostProcess -> ApplyIntensity(0) (no base light).
assert.deepEqual(sample(project, 30).member(1).rim, { intensity: 0 });
// Without any member lighting track the live baseline (ApplyIntensity(0) at
// initialization) holds; MVStudioScene passes null and SifasMaterial keeps 0.
assert.equal(sample({ quality: { values: {} }, tracks: [] }, 30).member(1), null);
// member_rim_light off only mutes the "Member Rim Light" tracks
// (LiveQualityOperator.ApplyLiveQualityToMemberEffectTrack 0x20f3164). The base
// light keeps writing every member's rim: LiveBaseLightMixer.PostProcess ->
// LiveBaseLightReciever.ApplyBaseLightColor -> ApplyBaseIntensity(base), so the
// material holds the base rim and ApplyEnable(base > 0) keeps the stencil Equal.
const baseRim = { start: 0, duration: 100, values: { playableClass: "LiveBaseLightClip", ambientColorType: 0,
  ambientMemberPosition: 1, ambientColor: [1, 1, 1, 1], ambientTintColor: [1, 1, 1, 1], rimlightColorType: 0,
  rimlightColor: [0.25, 0.5, 1, 1], rimlightIntensity: 0.4, rimlightSharpness: 6, rimlightDirection: { x: 1, y: 2, z: 3 } } };
const muted = { quality: { values: { member_rim_light: false, base_light: true } }, tracks: [...project.tracks,
  { nativeClass: "LiveBaseLightTrack", binding: "/EntryPoint/Live/Global/LiveBaseLightReciever", events: [baseRim] }] };
assert.deepEqual(sample(muted, 14.946).member(1).rim,
  { color: [0.25, 0.5, 1, 1], intensity: 0.4, power: 7, direction: [1, 2, 3, 0] },
  "with member rim light off the base light alone sets the rim (the local clip is muted)");
muted.quality.values.member_rim_light = true;
assert(Math.abs(sample(muted, 14.946).member(1).rim.intensity - (0.4 + 0.75)) < 1e-6, "with it on: base + local");
console.log("PASS: member rim mixing matches the 12035 Max 3D game dump (local clips, no base light)");
