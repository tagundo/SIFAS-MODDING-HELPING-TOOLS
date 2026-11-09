/* Original game cues follow the imported timeline, with local audio fallback. */
(function () {
  "use strict";
  var pending = null, api = null;
  var labels = {
    "Accompanying voice or music": ["연결된 대사·음악", "関連するボイス・音楽"],
    "Play audio with motion": ["모션과 함께 소리 재생", "モーションと一緒に音声を再生"],
    "Linked game audio": ["연결된 게임 음성·음악", "関連するゲーム音声・音楽"],
    "Local audio file": ["내 오디오 파일", "ローカル音声ファイル"],
    "Choose accompanying audio": ["다른 오디오 선택", "別の音声を選択"],
    "Volume": ["음량", "音量"], "Mute": ["음소거", "ミュート"],
    "Game audio loads automatically with its motion.": ["모션에 연결된 게임 음성·음악을 자동으로 불러옵니다.", "モーションに関連するゲーム音声・音楽を自動的に読み込みます。"],
    "No linked audio in this motion.": ["이 모션에는 연결된 소리가 없습니다.", "このモーションには関連する音声がありません。"],
    "Linked audio ready.": ["연결된 소리를 불러왔습니다.", "関連する音声を読み込みました。"],
    "Press Play to allow accompanying audio.": ["재생 버튼을 눌러 연결된 소리를 허용하세요.", "再生ボタンを押して音声再生を許可してください。"],
    "This audio format could not be played. Choose WAV, MP3 or OGG.": ["이 오디오 형식을 재생할 수 없습니다. WAV, MP3, OGG 파일을 선택하세요.", "この音声形式は再生できません。WAV、MP3、OGGを選択してください。"],
    "Choose an audio file smaller than 64 MB.": ["64MB보다 작은 오디오 파일을 선택하세요.", "64MB未満の音声ファイルを選択してください。"],
    "The linked audio response is invalid.": ["연결된 소리 정보를 불러오지 못했습니다.", "関連する音声情報が無効です。"]
  };
  function t(key) {
    var lang = document.documentElement.lang, index = lang === "ko" ? 0 : lang === "ja" ? 1 : -1;
    return index >= 0 && labels[key] ? labels[key][index] : typeof window.T === "function" ? window.T(key) : key;
  }
  function start() {
    var panel = document.getElementById("viewer-adjustments"); if (!panel || api) return;
    function make(tag, text, parent) { var el = document.createElement(tag); if (text) { el.textContent = t(text); el.dataset.motionAudioLabel = text; } if (parent) parent.appendChild(el); return el; }
    var box = make("details", null, panel); box.id = "viewer-motion-audio-controls"; box.className = "viewer-save-advanced";
    make("summary", "Accompanying voice or music", box);
    function checkbox(text, id) { var label = make("label", null, box), input = make("input", null, label); input.type = "checkbox"; input.id = id; make("span", text, label); return input; }
    var enabled = checkbox("Play audio with motion", "viewer-motion-audio-enabled"); enabled.checked = true;
    var selectLabel = make("label", null, box), select = make("select", null, selectLabel); select.id = "viewer-motion-audio-source";
    make("option", "Linked game audio", select).value = "game"; make("option", "Local audio file", select).value = "local";
    var volumeLabel = make("label", null, box); make("span", "Volume", volumeLabel);
    var volume = make("input", null, volumeLabel); volume.id = "viewer-motion-audio-volume"; volume.type = "range"; volume.min = "0"; volume.max = "1"; volume.step = ".01"; volume.value = "1";
    var muted = checkbox("Mute", "viewer-motion-audio-muted");
    var fileLabel = make("label", null, box); make("span", "Choose accompanying audio", fileLabel);
    var file = make("input", null, fileLabel); file.id = "viewer-motion-audio-file"; file.type = "file"; file.accept = "audio/*,.wav,.mp3,.ogg,.m4a,.flac";
    var help = make("p", "Game audio loads automatically with its motion.", box); help.className = "viewer-render-note";
    var status = make("p", null, box); status.id = "viewer-motion-audio-status"; status.className = "viewer-render-note"; status.setAttribute("role", "status");
    var tracks = [], local = null, localUrl = "", binding = { modelId: null, clipNames: [] }, warnings = [], blocked = false, dead = false;
    var frame = 0, timer = 0, currentStatus = "No linked audio in this motion.", transport = null, forceSeek = false;
    var preferenceKey = "elichika.viewer.motion-audio.v2";
    try { var preference = JSON.parse(localStorage.getItem(preferenceKey) || "null"); if (preference) { enabled.checked = preference.enabled !== false; muted.checked = preference.muted === true; if (typeof preference.volume === "number" && preference.volume >= 0 && preference.volume <= 1) volume.value = String(preference.volume); } } catch (_) {}
    function savePreference() { try { localStorage.setItem(preferenceKey, JSON.stringify({ enabled: enabled.checked, muted: muted.checked, volume: Number(volume.value) })); } catch (_) {} }
    function message(key) { currentStatus = key; status.textContent = t(key) + (warnings.length ? " " + warnings.join(" ") : ""); }
    function state() { return window.ModelViewer && (window.ModelViewer.getMotionState ? window.ModelViewer.getMotionState() : window.ModelViewer.getState()); }
    function chosen() { return select.value === "local" ? local ? [local] : [] : tracks; }
    function pauseAll() { tracks.concat(local ? [local] : []).forEach(function (track) { track.audio.pause(); }); }
    function stopTick() { if (frame) cancelAnimationFrame(frame); if (timer) clearTimeout(timer); frame = timer = 0; }
    function disposeTrack(track) { track.audio.pause(); track.audio.removeAttribute("src"); track.audio.load(); track.audio.remove(); }
    function audioTrack(data) {
      var audio = make("audio", null, box); audio.className = "viewer-motion-audio-player"; audio.preload = "auto"; audio.hidden = true;
      audio.src = data.url; audio.dataset.motionCue = data.cue || "";
      // The media decoder runs independently of rendering. Repeatedly seeking
      // it to a stepped/slow render clock cuts PCM even when all bytes are
      // already buffered. Only transport discontinuities seek; while playing,
      // the rig samples the active media clock through getPlaybackClock().
      var track = { data: data, audio: audio, starting: false, failed: false, synchronized: false, active: false, seeks: 0 };
      audio.addEventListener("loadedmetadata", arm);
      audio.addEventListener("error", function () { track.failed = true; message("This audio format could not be played. Choose WAV, MP3 or OGG."); });
      return track;
    }
    function isValid(playback, rig) {
      var valid = enabled.checked && !document.hidden && playback && playback.visible && !playback.loading && !playback.contextLost && !(playback.layout && playback.layout.minimized) && rig && rig.selectedClip;
      if (valid && select.value === "game") valid = (!binding.modelId || !playback.modelId || binding.modelId === playback.modelId) && (!binding.clipNames.length || binding.clipNames.indexOf(rig.selectedClip) >= 0);
      return !!valid;
    }
    function playbackClock(rig) {
      var playback = state(); rig = rig || playback && playback.rig;
      if (!isValid(playback, rig) || !rig.playing || !transport || !transport.playing || forceSeek ||
          transport.clip !== rig.selectedClip || transport.modelId !== playback.modelId || transport.revision !== rig.playbackRevision) return null;
      var selected = chosen();
      for (var index = 0; index < selected.length; index++) {
        var track = selected[index], data = track.data, audio = track.audio;
        if (!track.synchronized || track.failed || track.starting || audio.paused || audio.ended || audio.seeking || audio.readyState < 2) continue;
        var start = data.startTime || 0, offset = data.offset || 0, rate = data.playbackRate || 1;
        var clock = start + (audio.currentTime - offset) / rate;
        if (!Number.isFinite(clock) || clock < start || Number.isFinite(data.playDuration) && clock >= start + data.playDuration) continue;
        return clock;
      }
      return null;
    }
    function update() {
      frame = timer = 0; if (dead) return;
      var selected = chosen(), playback = state(), rig = playback && playback.rig, valid = isValid(playback, rig);
      var playing = valid && rig.playing, clock = rig ? Math.max(0, Number(rig.time) || 0) : 0;
      var discontinuity = forceSeek || !transport || transport.clip !== (rig && rig.selectedClip) ||
        transport.modelId !== (playback && playback.modelId) || transport.revision !== (rig && rig.playbackRevision) ||
        transport.playing !== !!playing || clock < transport.time - .05;
      forceSeek = false;
      tracks.concat(local ? [local] : []).forEach(function (track) {
        var audio = track.audio, data = track.data;
        audio.volume = Number(volume.value); audio.muted = muted.checked;
        if (!valid || selected.indexOf(track) < 0 || track.failed) { audio.pause(); track.synchronized = false; track.active = false; return; }
        var duration = Number.isFinite(data.playDuration) ? data.playDuration : Number.isFinite(audio.duration) ? audio.duration : Infinity;
        var start = data.startTime || 0, offset = data.offset || 0, rate = data.playbackRate || 1;
        var waiting = clock < start, finished = clock >= start + duration, position = offset + Math.max(0, clock - start) * rate;
        if (Number.isFinite(audio.duration) && position >= audio.duration - .002) finished = true;
        if (audio.playbackRate !== rate) audio.playbackRate = rate;
        if (waiting || finished || !playing) audio.pause();
        // A retry after an interrupted play promise must not restart an
        // asynchronous seek every render frame and starve the decoder.
        var active = playing && !waiting && !finished, beginning = active && !track.active;
        track.active = active;
        var seek = !track.synchronized || discontinuity || beginning || !playing && Math.abs(audio.currentTime - position) > .002 ||
          waiting && Math.abs(audio.currentTime - offset) > .002;
        if (audio.readyState >= 1 && seek) {
          var target = waiting ? offset : Math.max(0, Math.min(position, Number.isFinite(audio.duration) ? audio.duration : position));
          try {
            if (Math.abs(audio.currentTime - target) > .002) {
              audio.currentTime = target; track.seeks++;
              track.lastSeekReason = !track.synchronized ? "initial" : discontinuity ? "transport" : beginning ? "start" : "paused";
            }
            track.synchronized = true;
          } catch (_) {}
        }
        if (playing && !waiting && !finished && audio.paused && !track.starting && !blocked && audio.readyState >= 2) {
          track.starting = true;
          var play = audio.play();
          if (play && play.then) play.then(function () { track.starting = false; }).catch(function (error) { track.starting = false; if (error.name !== "AbortError") { blocked = true; message("Press Play to allow accompanying audio."); } });
          else track.starting = false;
        }
      });
      transport = { clip: rig && rig.selectedClip, modelId: playback && playback.modelId, revision: rig && rig.playbackRevision,
        playing: !!playing, time: clock };
      if (enabled.checked && selected.length) {
        if (playing) frame = requestAnimationFrame(update);
        else timer = setTimeout(update, document.hidden ? 500 : 100);
      }
    }
    function arm(seek) { if (seek === true) forceSeek = true; stopTick(); update(); }
    function bind(options) {
      var playback = state(), rig = playback && playback.rig;
      binding = { modelId: options && options.modelId || playback && playback.modelId || null,
        clipNames: options && Array.isArray(options.clipNames) ? options.clipNames.slice() : rig && rig.selectedClip ? [rig.selectedClip] : [] };
    }
    function load(descriptor, options) {
      if (!descriptor || descriptor.version !== 1 || !Array.isArray(descriptor.tracks) || descriptor.tracks.length > 32) throw new Error(t("The linked audio response is invalid."));
      var next = descriptor.tracks.map(function (data) {
        if (!data || typeof data.url !== "string" || !/^\/api\/viewer\/game\/motions\/audio\/[a-f0-9]{32}\.wav$/.test(data.url) ||
            ![data.startTime, data.offset, data.playDuration, data.playbackRate].every(function (number) { return typeof number === "number" && Number.isFinite(number) && number >= 0; }) || data.playbackRate < .05 || data.playbackRate > 8) throw new Error(t("The linked audio response is invalid."));
        return data;
      });
      pauseAll(); tracks.forEach(disposeTrack); tracks = next.map(audioTrack); transport = null;
      warnings = Array.isArray(descriptor.warnings) ? descriptor.warnings.filter(function (w) { return typeof w === "string"; }).slice(0, 32) : [];
      select.value = "game"; blocked = false; bind(options); message(tracks.length ? "Linked audio ready." : "No linked audio in this motion."); arm();
    }
    file.addEventListener("change", function () {
      if (local) disposeTrack(local); local = null; if (localUrl) URL.revokeObjectURL(localUrl); localUrl = "";
      var selected = file.files && file.files[0];
      if (selected && selected.size > 64 * 1024 * 1024) { message("Choose an audio file smaller than 64 MB."); arm(); return; }
      if (selected) { localUrl = URL.createObjectURL(selected); local = audioTrack({ url: localUrl, cue: selected.name, startTime: 0, offset: 0, playbackRate: 1 }); enabled.checked = true; select.value = "local"; blocked = false; warnings = []; status.textContent = selected.name; }
      arm();
    });
    [enabled, muted, volume, select].forEach(function (input) { input.addEventListener(input === volume ? "input" : "change", function () { blocked = false; savePreference(); arm(); }); });
    document.addEventListener("visibilitychange", arm);
    document.addEventListener("click", function (event) { if (event.target.closest && event.target.closest("#viewer-play, #viewer-pose-basic, #viewer-pose-preview")) { blocked = false; arm(); } });
    document.addEventListener("input", function (event) { if (event.target.id === "viewer-time") arm(true); });
    document.addEventListener("change", function (event) { if (event.target.id === "viewer-motion") { blocked = false; arm(true); } });
    new MutationObserver(function () { box.querySelectorAll("[data-motion-audio-label]").forEach(function (el) { el.textContent = t(el.dataset.motionAudioLabel); }); message(currentStatus); }).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    window.addEventListener("pagehide", function () { dead = true; stopTick(); pauseAll(); if (localUrl) URL.revokeObjectURL(localUrl); });
    api = { load: load, clear: function () { pauseAll(); tracks.forEach(disposeTrack); tracks = []; warnings = []; message("No linked audio in this motion."); arm(); },
      sync: function () { arm(true); }, getPlaybackClock: playbackClock,
      getState: function () { var selected = chosen(), first = selected[0]; return { enabled: enabled.checked, loaded: !!selected.length, paused: !selected.some(function (track) { return !track.audio.paused; }), time: first ? first.audio.currentTime : 0, blocked: blocked, source: select.value, muted: muted.checked, volume: Number(volume.value), tracks: selected.map(function (track) { return { cue: track.data.cue, paused: track.audio.paused, time: track.audio.currentTime, startTime: track.data.startTime, duration: track.audio.duration, readyState: track.audio.readyState, seeks: track.seeks, lastSeekReason: track.lastSeekReason || null, error: track.failed }; }), warnings: warnings.slice() }; } };
    message(currentStatus);
    if (pending) { var request = pending; pending = null; load(request.descriptor, request.options); }
  }
  window.ViewerMotionAudio = { load: function (descriptor, options) { if (api) return api.load(descriptor, options); pending = { descriptor: descriptor, options: options }; },
    clear: function () { pending = null; if (api) api.clear(); }, sync: function () { if (api) api.sync(); },
    getPlaybackClock: function (state) { return api ? api.getPlaybackClock(state) : null; },
    getState: function () { return api ? api.getState() : { loaded: false, enabled: true, paused: true, tracks: [] }; } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
}());
