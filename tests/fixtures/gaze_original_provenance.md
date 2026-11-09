Gaze constants and target semantics were read from SIFAS GL3.12's unchanged
ARM64 IL2CPP24.1 metadata/native functions. No game binary is included here.

- `GazingTarget`: Camera21, Audience22, fixedUp31/Down32/Left33/Right34,
  LeftUp35/RightUp36, members1..12 and split-screen cameras37..40.
- `GazeDirection`: Right0/Left1/Up2/Down3/RightUp4/LeftUp5.
- `MemberEyeContactBase`: horizontal45degrees, vertical30degrees, zero-vector
  tolerance0.001. Its six original iris animation suffixes are006..011.
- `LiveMemberEyeContact.CalcWeight` at0x29987c4 and Navi equivalent0x2ca9ab4
  map fixed targets into those original pose inputs.
- Target-position paths `LiveMemberEyeContact.RotateEyeToTarget` at0x2998c58
  and Navi at0x2ca96f0 use face-local normalized direction, atan2(x,z)/45 and
  atan2(y,hypot(x,z))/30, clamp each to[-1,1], then divide both by the sum of
  absolute weights when that sum exceeds1.
- `LiveMemberEyeContact.Initialize` at0x29978fc finds `Eye_Root` and stores its
  Transform as the gaze reference. The referenced literal was independently
  resolved from GOT0x7069250 -> storage0x75a26c0 -> metadataUsage95919 ->
  stringLiteral7617 (`Eye_Root`). Real faces' Head_Face bone is rotated90degrees;
  using that bone instead swaps horizontal/vertical motion. Neutral custom rigs
  without Eye_Root use their available Face_Root/Head_Face reference.

The editor preserves its mirrored coordinate system and samples actual loaded
iris pose clips; eyelid/mouth tracks are excluded. The preview camera is the
Camera target in this single-model viewer. Original audience, other-performer
and split-screen scene targets require explicit available scene positions;
missing positions are reported, never inferred from another performer.
When a retained motion targets a different character and the displayed face's
own original six-pose bank is verified, its common direction semantics rebind
to that bank. Old absolute iris positions are not reused on the new face.

This is source-derived equation/reference coverage, not isolated native-function
execution or a claim to reproduce the original MV stage/camera scene.
