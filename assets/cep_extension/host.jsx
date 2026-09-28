/**
 * Premiere Pro ExtendScript Host (`assets/cep_extension/host.jsx`)
 *
 * Supports LIVE STEP-BY-STEP Timeline Construction inside Adobe Premiere Pro:
 * - Creates Project Panel Bins (`01_A_Roll`, `02_B_Roll`, `03_Audio_SFX_BGM`, `04_Graphics`)
 * - Imports clips and sets exact In/Out points (`254016000000` ticks/second)
 * - Places clips one-by-one onto V1, V2, V3, A1, A2, A3
 * - Scrubs the Timeline Playhead (`seq.setPlayerPosition`) on every cut so the user watches
 *   the edit happen live in the Timeline and Program Monitor
 * - Sets `Motion -> Scale` (punch-in zooms) and `Volume -> Level` (audio gain/ducking) with `updateUI = true`
 * - Adds color-coded Sequence Markers live on the timeline ruler
 */

var TICKS_PER_SEC = 254016000000;

function _escJson(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/\\/g, "\\\\")
        .replace(/"/g, '\\"')
        .replace(/\r/g, "\\r")
        .replace(/\n/g, "\\n")
        .replace(/\t/g, "\\t");
}

function _toJson(val) {
    if (val === null || val === undefined) return "null";
    if (typeof val === "number") return isFinite(val) ? String(val) : "null";
    if (typeof val === "boolean") return val ? "true" : "false";
    if (typeof val === "string") return '"' + _escJson(val) + '"';
    if (val instanceof Array) {
        var a = [];
        for (var i = 0; i < val.length; i++) a.push(_toJson(val[i]));
        return "[" + a.join(",") + "]";
    }
    if (typeof val === "object") {
        var o = [];
        for (var k in val) {
            if (val.hasOwnProperty(k)) o.push('"' + _escJson(k) + '":' + _toJson(val[k]));
        }
        return "{" + o.join(",") + "}";
    }
    return "null";
}

function _secToTicks(sec) {
    return String(Math.round(Number(sec || 0) * TICKS_PER_SEC));
}

function _findOrCreateBin(binName) {
    var root = app.project.rootItem;
    for (var i = 0; i < root.children.numItems; i++) {
        var child = root.children[i];
        if (child.type === ProjectItemType.BIN && child.name === binName) {
            return child;
        }
    }
    return root.createBin(binName);
}

function _findProjectItemByPath(filePath, searchFolder) {
    var folder = searchFolder || app.project.rootItem;
    var normTarget = String(filePath).replace(/\\/g, "/").toLowerCase();
    var baseName = normTarget.split("/").pop();

    for (var i = 0; i < folder.children.numItems; i++) {
        var item = folder.children[i];
        if (item.type === ProjectItemType.BIN) {
            var foundSub = _findProjectItemByPath(filePath, item);
            if (foundSub) return foundSub;
        } else {
            try {
                var mediaPath = String(item.getMediaPath()).replace(/\\/g, "/").toLowerCase();
                if (mediaPath === normTarget || String(item.name).toLowerCase() === baseName) {
                    return item;
                }
            } catch (e) {}
        }
    }
    return null;
}

function _ensureProjectItem(filePath, binName) {
    var existing = _findProjectItemByPath(filePath);
    if (existing) return existing;
    var targetBin = binName ? _findOrCreateBin(binName) : app.project.rootItem;
    app.project.importFiles([filePath], true, targetBin, false);
    return _findProjectItemByPath(filePath, targetBin) || _findProjectItemByPath(filePath);
}

function _applyScaleAndGainOnTrackClip(track, clipStartSec, scalePct, gainDb) {
    try {
        for (var i = track.clips.numItems - 1; i >= 0; i--) {
            var c = track.clips[i];
            if (Math.abs(c.start.seconds - clipStartSec) < 0.15) {
                for (var compIdx = 0; compIdx < c.components.numItems; compIdx++) {
                    var comp = c.components[compIdx];
                    if (scalePct && Math.abs(scalePct - 100.0) > 0.1 && comp.displayName === "Motion") {
                        for (var pIdx = 0; pIdx < comp.properties.numItems; pIdx++) {
                            var prop = comp.properties[pIdx];
                            if (prop.displayName === "Scale") {
                                prop.setValue(Number(scalePct), true);
                            }
                        }
                    }
                    if (gainDb !== undefined && gainDb !== null && comp.displayName === "Volume") {
                        for (var vpIdx = 0; vpIdx < comp.properties.numItems; vpIdx++) {
                            var vprop = comp.properties[vpIdx];
                            if (vprop.displayName === "Level") {
                                // Premiere Volume Level internal value is linear amplitude (0dB ~ 0.17782794)
                                var linearVal = 0.177827941 * Math.pow(10.0, Number(gainDb) / 20.0);
                                vprop.setValue(linearVal, true);
                            }
                        }
                    }
                }
                break;
            }
        }
    } catch (e) {}
}

function pproPing() {
    try {
        var projName = (app.project && app.project.name) ? String(app.project.name) : "Untitled";
        var seqName = (app.project && app.project.activeSequence) ? String(app.project.activeSequence.name) : null;
        return _toJson({
            status: "success",
            version: String(app.version),
            projectName: projName,
            activeSequence: seqName
        });
    } catch (e) {
        return _toJson({ status: "error", message: String(e) });
    }
}

function pproLivePlaceClip(specJsonStr) {
    try {
        var s = eval("(" + specJsonStr + ")");
        var seq = app.project.activeSequence;
        if (!seq && app.project.sequences.numSequences > 0) {
            seq = app.project.sequences[0];
            app.project.activeSequence = seq;
        }

        var item = _ensureProjectItem(s.path, s.binName || "01_Media");
        if (!item) {
            return _toJson({ status: "error", message: "Could not import or locate media: " + s.path });
        }

        // If no sequence exists yet, create one from the first clip!
        if (!seq) {
            seq = app.project.createNewSequenceFromClips(s.sequenceName || "Live_AI_Edit", [item], app.project.rootItem);
            app.project.activeSequence = seq;
            // Remove the initial full-length clip placed by createNewSequenceFromClips so we place exact cuts
            try {
                if (seq.videoTracks[0].clips.numItems > 0) seq.videoTracks[0].clips[0].remove(false, false);
                if (seq.audioTracks[0].clips.numItems > 0) seq.audioTracks[0].clips[0].remove(false, false);
            } catch (eRem) {}
        }

        if (s.width && s.height) {
            try {
                var settings = seq.getSettings();
                if (settings) {
                    settings.videoFrameWidth = Number(s.width);
                    settings.videoFrameHeight = Number(s.height);
                    seq.setSettings(settings);
                }
            } catch (eSet) {}
        }

        var inSec = Number(s.inSec || 0);
        var outSec = Number(s.outSec || (inSec + Number(s.durationSec || 3.0)));
        var startSec = Number(s.startSec || 0);

        try {
            item.setInPoint(_secToTicks(inSec), 4);
            item.setOutPoint(_secToTicks(outSec), 4);
        } catch (eInOut) {}

        var trackType = String(s.trackType || "video").toLowerCase();
        var trackIndex = Number(s.trackIndex || 0);

        if (trackType === "video") {
            var vTrack = seq.videoTracks[Math.min(trackIndex, seq.videoTracks.numTracks - 1)];
            vTrack.overwriteClip(item, startSec);
            if (s.scale && Math.abs(Number(s.scale) - 100.0) > 0.1) {
                _applyScaleAndGainOnTrackClip(vTrack, startSec, Number(s.scale), null);
            }
            if (s.gainDb !== undefined && seq.audioTracks.numTracks > 0) {
                _applyScaleAndGainOnTrackClip(seq.audioTracks[0], startSec, null, Number(s.gainDb));
            }
        } else {
            var aTrack = seq.audioTracks[Math.min(trackIndex, seq.audioTracks.numTracks - 1)];
            aTrack.overwriteClip(item, startSec);
            if (s.gainDb !== undefined) {
                _applyScaleAndGainOnTrackClip(aTrack, startSec, null, Number(s.gainDb));
            }
        }

        // Scrub the playhead to the newly placed cut so the user sees it live in the Program Monitor!
        try {
            seq.setPlayerPosition(_secToTicks(startSec));
        } catch (ePos) {}

        return _toJson({
            status: "success",
            placedClip: item.name,
            trackType: trackType,
            trackIndex: trackIndex + 1,
            startSec: startSec,
            durationSec: Number((outSec - inSec).toFixed(3))
        });
    } catch (e) {
        return _toJson({ status: "error", message: String(e) });
    }
}

function pproLiveAddMarker(specJsonStr) {
    try {
        var m = eval("(" + specJsonStr + ")");
        var seq = app.project.activeSequence;
        if (!seq) return _toJson({ status: "error", message: "No active sequence" });
        var marker = seq.markers.createMarker(Number(m.timeSec || 0));
        marker.name = String(m.name || "Beat");
        marker.comments = String(m.comment || "");
        try { marker.setColorByIndex(Number(m.colorIndex || 1)); } catch (eC) {}
        seq.setPlayerPosition(_secToTicks(Number(m.timeSec || 0)));
        return _toJson({ status: "success", marker: marker.name, timeSec: m.timeSec });
    } catch (e) {
        return _toJson({ status: "error", message: String(e) });
    }
}

function pproSetPlayhead(sec) {
    try {
        var seq = app.project.activeSequence;
        if (seq) seq.setPlayerPosition(_secToTicks(Number(sec || 0)));
        return _toJson({ status: "success", playheadSec: Number(sec || 0) });
    } catch (e) {
        return _toJson({ status: "error", message: String(e) });
    }
}

function pproInspectActiveSequence() {
    try {
        if (!app.project || !app.project.activeSequence) {
            return _toJson({ status: "error", message: "No active sequence open in Premiere Pro." });
        }
        var seq = app.project.activeSequence;
        var vTracks = [];
        var allClipDurations = [];

        for (var v = 0; v < seq.videoTracks.numTracks; v++) {
            var vt = seq.videoTracks[v];
            var clips = [];
            for (var c = 0; c < vt.clips.numItems; c++) {
                var clip = vt.clips[c];
                var dur = clip.duration.seconds;
                if (v === 0 && dur > 0) allClipDurations.push(dur);
                clips.push({
                    name: clip.name,
                    startSec: Number(clip.start.seconds.toFixed(3)),
                    endSec: Number(clip.end.seconds.toFixed(3)),
                    inPointSec: Number(clip.inPoint.seconds.toFixed(3)),
                    outPointSec: Number(clip.outPoint.seconds.toFixed(3)),
                    durationSec: Number(dur.toFixed(3))
                });
            }
            vTracks.push({
                index: v + 1,
                name: vt.name || ("V" + (v + 1)),
                clipCount: vt.clips.numItems,
                clips: clips
            });
        }

        var aTracks = [];
        for (var a = 0; a < seq.audioTracks.numTracks; a++) {
            var at = seq.audioTracks[a];
            var aClips = [];
            for (var ac = 0; ac < at.clips.numItems; ac++) {
                var aclip = at.clips[ac];
                aClips.push({
                    name: aclip.name,
                    startSec: Number(aclip.start.seconds.toFixed(3)),
                    endSec: Number(aclip.end.seconds.toFixed(3)),
                    durationSec: Number(aclip.duration.seconds.toFixed(3))
                });
            }
            aTracks.push({
                index: a + 1,
                name: at.name || ("A" + (a + 1)),
                clipCount: at.clips.numItems,
                clips: aClips
            });
        }

        var sumDur = 0;
        for (var d = 0; d < allClipDurations.length; d++) sumDur += allClipDurations[d];
        var avgShotLen = allClipDurations.length > 0 ? Number((sumDur / allClipDurations.length).toFixed(2)) : 0;

        return _toJson({
            status: "success",
            projectName: app.project.name,
            sequenceName: seq.name,
            frameSizeHorizontal: seq.frameSizeHorizontal,
            frameSizeVertical: seq.frameSizeVertical,
            averageShotLengthSec: avgShotLen,
            totalV1Cuts: allClipDurations.length,
            videoTracks: vTracks,
            audioTracks: aTracks
        });
    } catch (e) {
        return _toJson({ status: "error", message: String(e) });
    }
}

function pproImportXmlOrFiles(pathsJsonStr) {
    try {
        var paths = eval("(" + pathsJsonStr + ")");
        var ok = app.project.importFiles(paths, true, app.project.rootItem, false);
        return _toJson({
            status: ok ? "success" : "partial",
            importedPaths: paths,
            projectName: app.project.name
        });
    } catch (e) {
        return _toJson({ status: "error", message: String(e) });
    }
}
