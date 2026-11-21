(function (global) {
  "use strict";

  const mainCamera = "/EntryPoint/Live/Cameras/MainCamera";
  const enabled = (value) => value === true || value === 1;

  function sample(project, time, fov, memberDistance) {
    if (project?.quality?.values?.posteffect !== true || !global.MVStudioLighting?.nativeWeight) return null;
    const tracks = project.tracks.filter(track => !track.muted && track.binding === mainCamera &&
      track.nativeClass === "LiveDepthOfFieldTrack");
    if (tracks.length !== 1) return null;

    let highest = 0, discrete, distance = 0, aperture = 0, focalLength = 0;
    for (const event of tracks[0].events) {
      const value = event.values;
      if (value?.playableClass !== "LiveDepthOfFieldClip") continue;
      const weight = global.MVStudioLighting.nativeWeight(event, time);
      if (!(weight > 0)) continue;
      let focus = value.focusDistance;
      if (enabled(value.useMemberDistance)) {
        // Explicit member targeting uses the current pose immediately. The
        // native transition state only applies to automatic member selection.
        if (value.cameraAutoDistanceMode !== 0 || ![0, 3].includes(value.bodyPart)) return null;
        focus = memberDistance(value.memberPosition, value.bodyPart);
        if (Number.isFinite(focus)) focus -= 0.1;
      }
      if (![focus, value.aperture, value.focalLength].every(Number.isFinite)) return null;
      distance = Math.fround(distance + Math.fround(focus * weight));
      aperture = Math.fround(aperture + Math.fround(value.aperture * weight));
      focalLength = Math.fround(focalLength + Math.fround(value.focalLength * weight));
      if (weight > highest) {
        highest = weight;
        discrete = value;
      }
    }
    if (!discrete || ![0, 1, 2, 3].includes(discrete.kernelSize)) return null;
    const focal = enabled(discrete.useCameraFov) ? 0.012 / Math.tan(fov * Math.PI / 360) : focalLength / 1000;
    return focal > 0 && Number.isFinite(focal) ? { distance, aperture, focalLength: focal,
      kernelSize: discrete.kernelSize, antiAura: enabled(discrete.antiAura) } : null;
  }

  global.MVStudioDofFocus = { sample };
})(typeof window !== "undefined" ? window : globalThis);
