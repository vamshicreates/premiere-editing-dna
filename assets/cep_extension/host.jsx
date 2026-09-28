/**
 * Premiere Pro ExtendScript Host (`assets/cep_extension/host.jsx`)
 * Exposes sequence DNA inspection, XML/media import, marker creation, and custom ExtendScript execution.
 */

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
