"use strict";
/* LiveCoreMemberManager.MemberMax = 12: performer props bind Member10..Member12 too. */

const assert = require("node:assert/strict");

global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
const {create} = (require("../webtools/web/static/mv-studio-prop-light.js"), global.MVStudioPropLight);

const prop = (slot) => `/EntryPoint/Live/Members/ske_so2028/Member${slot}/Model/Reference/Move/RightHand/chp0001`;
for (const slot of [1, 9, 10, 12]) assert.notEqual(create(prop(slot), slot), null, `Member${slot} prop light`);
assert.equal(create(prop(12), 1), null, "the binding slot must match the performer");
assert.equal(create(prop(1), 12), null, "Member1 is not Member12");
console.log("MV Studio performer props reach Member12");
