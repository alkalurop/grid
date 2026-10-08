//! Replace the beat grid rekordbox loads for each track.
//!
//! The DAT's `PQTZ` section is what the FLX10 reads. Cue lists and waveforms
//! stay. A stale `PQT2` extended grid is removed so it cannot sit beside the
//! new one. BPM on the collection row is updated. Key is left alone.
//!
//! Tracks that have no analysis file yet are skipped. This command does not
//! invent waveforms for them.

use std::collections::HashMap;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use rbl_anlz::Beat;
use rbl_core::FourCc;
use rbl_db::Library;
use rusqlite::{params, Connection, TransactionBehavior};
use serde::Deserialize;

const USN_TABLES: &[&str] = &[
    "djmdContent",
    "djmdPlaylist",
    "djmdSongPlaylist",
    "djmdSongHotCueBanklist",
];
const ANALYSED_FULL: i64 = 105;
const CONTENT_LINK_LOCAL: i64 = 0x002c_0600;

#[derive(Deserialize)]
struct Job {
    tracks: Vec<JobTrack>,
}

#[derive(Deserialize)]
struct JobTrack {
    path: String,
    beats: Vec<JobBeat>,
}

#[derive(Deserialize)]
struct JobBeat {
    n: u16,
    ms: u32,
    bpm: f64,
}

#[derive(Clone)]
struct Row {
    id: String,
    analysis_path: String,
}

struct Planned {
    id: String,
    analysis_path: String,
    bpm_x100: i64,
}

pub fn commit_rekordbox() -> Result<String, String> {
    if rekordbox_app_is_running() {
        return Err("Rekordbox is open. Quit it before writing beatgrids.".to_string());
    }
    // The agent stays up after quit and the database opener treats that as
    // rekordbox running. Arm the override only after the app itself is gone.
    // A locked database still fails on its own.
    std::env::set_var(rbl_db::UNSAFE_WRITES_ENV, "1");
    if !rbl_db::enable_unsafe_writes() {
        return Err("could not arm the rekordbox library write".to_string());
    }

    let job = read_job()?;
    if job.tracks.is_empty() {
        return Err("no tracks to write".to_string());
    }
    let location = rbl_db::detect().map_err(|err| err.to_string())?;
    let mut library = Library::open(location.clone(), rbl_db::OpenMode::ReadWrite)
        .map_err(|err| err.to_string())?;
    let backup = backup_library(library.connection())?;
    eprintln!("backup  {}", backup.display());

    let cloud = rbl_db::cloud_contents_root();
    let index = index_tracks(library.connection(), cloud.as_deref())?;
    let mut planned = Vec::new();
    let mut missing = 0_u32;
    let mut skipped = 0_u32;
    for track in &job.tracks {
        let Some(row) = lookup(&index, Path::new(&track.path)) else {
            missing += 1;
            eprintln!("missing  {}", track.path);
            continue;
        };
        let beats = to_beats(&track.beats)?;
        let relative = analysis_path(library.connection(), row)?;
        let dat = rbl_anlz::resolve(&location.share_root, &relative);
        if !dat.is_file() {
            skipped += 1;
            eprintln!("no analysis file  {}", track.path);
            continue;
        }
        write_grid(&dat, &beats).map_err(|err| format!("{}: {err}", track.path))?;
        planned.push(Planned {
            id: row.id.clone(),
            analysis_path: relative,
            bpm_x100: bpm_x100(&track.beats)?,
        });
    }
    if planned.is_empty() {
        return Err("no rekordbox analysis files to update".to_string());
    }
    apply_rows(&mut library, &planned)?;
    Ok(serde_json::json!({
        "wrote": planned.len(),
        "missing": missing,
        "skipped": skipped,
    })
    .to_string())
}

fn read_job() -> Result<Job, String> {
    let mut raw = String::new();
    io::stdin()
        .read_to_string(&mut raw)
        .map_err(|err| err.to_string())?;
    serde_json::from_str(&raw).map_err(|err| format!("commit JSON: {err}"))
}

fn to_beats(beats: &[JobBeat]) -> Result<Vec<Beat>, String> {
    if beats.is_empty() {
        return Err("a track has no beats".to_string());
    }
    let mut out = Vec::with_capacity(beats.len());
    for beat in beats {
        if !(1..=4).contains(&beat.n) || beat.bpm <= 0.0 {
            return Err(format!("beat out of range: n={} bpm={}", beat.n, beat.bpm));
        }
        let tempo_x100 = u16::try_from((beat.bpm * 100.0).round() as i64).unwrap_or(0);
        if tempo_x100 == 0 {
            return Err("beat bpm is zero".to_string());
        }
        out.push(Beat {
            beat_number: beat.n,
            tempo_x100,
            time_ms: beat.ms,
        });
    }
    Ok(out)
}

fn bpm_x100(beats: &[JobBeat]) -> Result<i64, String> {
    let bpm = beats.first().map(|beat| beat.bpm).unwrap_or(0.0);
    let value = (bpm * 100.0).round();
    if value <= 0.0 || value > f64::from(u32::MAX) {
        return Err("bpm is out of range".to_string());
    }
    Ok(value as i64)
}

fn analysis_path(conn: &Connection, row: &Row) -> Result<String, String> {
    if !row.analysis_path.is_empty() {
        return Ok(row.analysis_path.clone());
    }
    let uuid: String = conn
        .query_row(
            "SELECT IFNULL(UUID, '') FROM djmdContent WHERE ID = ?1 AND rb_local_deleted = 0",
            [&row.id],
            |record| record.get(0),
        )
        .map_err(|err| err.to_string())?;
    match (uuid.get(..3), uuid.get(3..)) {
        (Some(head), Some(tail)) if !tail.is_empty() => {
            Ok(format!("/PIONEER/USBANLZ/{head}/{tail}/ANLZ0000.DAT"))
        }
        _ => Err(format!("{} has no analysis path", row.id)),
    }
}

fn write_grid(dat: &Path, beats: &[Beat]) -> Result<(), String> {
    let existing = rbl_anlz::Anlz::read(dat).map_err(|err| err.to_string())?;
    let bytes = existing.with_beat_grid(beats);
    rbl_core::durable::write(dat, &bytes).map_err(|err| err.to_string())?;
    drop_extended_grid(&rbl_anlz::sibling(dat, "EXT"))?;
    Ok(())
}

fn drop_extended_grid(path: &Path) -> Result<(), String> {
    if !path.is_file() {
        return Ok(());
    }
    let mut file = rbl_anlz::Anlz::read(path).map_err(|err| err.to_string())?;
    let before = file.sections.len();
    file.sections
        .retain(|section| section.tag != FourCc::new(b"PQT2"));
    if file.sections.len() == before {
        return Ok(());
    }
    rbl_core::durable::write(path, &file.to_bytes()).map_err(|err| err.to_string())
}

fn apply_rows(library: &mut Library, planned: &[Planned]) -> Result<(), String> {
    let stamp = utc_stamp();
    let tx = library
        .connection_mut()
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| err.to_string())?;
    for row in planned {
        let usn = next_usn(&tx)?;
        let updated = tx
            .execute(
                "UPDATE djmdContent SET
                    BPM = ?1,
                    KeyID = COALESCE(?2, KeyID),
                    AnalysisDataPath = ?3,
                    Length = COALESCE(?4, Length),
                    Analysed = CASE
                        WHEN (COALESCE(Analysed, 0) & 127) IN (0, 1)
                        THEN (COALESCE(Analysed, 0) & 128) | ?5
                        ELSE Analysed
                    END,
                    ContentLink = COALESCE(ContentLink, ?6),
                    AnalysisUpdated = CAST(COALESCE(AnalysisUpdated, '0') AS INTEGER) + 1,
                    rb_local_usn = ?7,
                    updated_at = ?8
                 WHERE ID = ?9 AND rb_local_deleted = 0",
                params![
                    row.bpm_x100,
                    None::<i64>,
                    row.analysis_path,
                    None::<i64>,
                    ANALYSED_FULL,
                    CONTENT_LINK_LOCAL,
                    usn,
                    stamp,
                    row.id,
                ],
            )
            .map_err(|err| err.to_string())?;
        if updated != 1 {
            return Err(format!("track {} was not updated", row.id));
        }
        set_counter(&tx, usn, &stamp)?;
    }
    tx.commit().map_err(|err| err.to_string())?;
    Ok(())
}

fn next_usn(conn: &Connection) -> Result<i64, String> {
    let counter: i64 = conn
        .query_row(
            "SELECT COALESCE(int_1, 0) FROM agentRegistry WHERE registry_id = 'localUpdateCount'",
            [],
            |record| record.get(0),
        )
        .map_err(|err| err.to_string())?;
    let mut highest = counter;
    for table in USN_TABLES {
        let exists: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?1",
                [table],
                |record| record.get(0),
            )
            .map_err(|err| err.to_string())?;
        if exists == 0 {
            continue;
        }
        let max: i64 = conn
            .query_row(
                &format!("SELECT COALESCE(MAX(rb_local_usn), 0) FROM {table}"),
                [],
                |record| record.get(0),
            )
            .map_err(|err| err.to_string())?;
        highest = highest.max(max);
    }
    highest
        .checked_add(1)
        .ok_or_else(|| "local update counter overflow".to_string())
}

fn set_counter(conn: &Connection, usn: i64, stamp: &str) -> Result<(), String> {
    let rows = conn
        .execute(
            "UPDATE agentRegistry SET int_1 = ?1, updated_at = ?2 WHERE registry_id = 'localUpdateCount'",
            params![usn, stamp],
        )
        .map_err(|err| err.to_string())?;
    if rows != 1 {
        return Err("missing local update counter".to_string());
    }
    Ok(())
}

fn index_tracks(conn: &Connection, cloud: Option<&Path>) -> Result<HashMap<PathBuf, Row>, String> {
    let mut statement = conn
        .prepare(
            "SELECT CAST(ID AS TEXT), IFNULL(FolderPath, ''), IFNULL(FileNameL, ''), IFNULL(AnalysisDataPath, '')
             FROM djmdContent WHERE rb_local_deleted = 0",
        )
        .map_err(|err| err.to_string())?;
    let rows = statement
        .query_map([], |record| {
            Ok((
                record.get::<_, String>(0)?,
                record.get::<_, String>(1)?,
                record.get::<_, String>(2)?,
                record.get::<_, String>(3)?,
            ))
        })
        .map_err(|err| err.to_string())?;
    let mut index = HashMap::new();
    for row in rows {
        let (id, folder, file, analysis_path) = row.map_err(|err| err.to_string())?;
        let stored = Row { id, analysis_path };
        for path in stored_paths(&folder, &file, cloud) {
            index.insert(normalize(&path), stored.clone());
            index.insert(path, stored.clone());
        }
    }
    Ok(index)
}

fn lookup<'a>(index: &'a HashMap<PathBuf, Row>, audio: &Path) -> Option<&'a Row> {
    let normalized = normalize(audio);
    index.get(&normalized).or_else(|| index.get(audio))
}

fn stored_paths(folder: &str, file: &str, cloud: Option<&Path>) -> Vec<PathBuf> {
    let folder = rbl_db::resolve_folder_path(&decode_location(folder), cloud);
    let file = decode_location(file);
    if folder.is_empty() {
        return Vec::new();
    }
    let mut paths = vec![PathBuf::from(&folder).join(&file)];
    if folder.ends_with(&file) {
        paths.push(PathBuf::from(folder));
    }
    paths
}

fn decode_location(value: &str) -> String {
    let text = value
        .trim()
        .strip_prefix("file://localhost")
        .or_else(|| value.trim().strip_prefix("file://"))
        .unwrap_or(value.trim());
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            if let Ok(byte) = u8::from_str_radix(
                std::str::from_utf8(&bytes[index + 1..index + 3]).unwrap_or(""),
                16,
            ) {
                out.push(byte);
                index += 3;
                continue;
            }
        }
        out.push(bytes[index]);
        index += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn normalize(path: &Path) -> PathBuf {
    std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
}

fn backup_library(conn: &Connection) -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME").ok_or("HOME is not set")?;
    let dir = PathBuf::from(home).join("local_tools/grid/rekordbox-backups");
    rbl_core::durable::create_dir_all(&dir).map_err(|err| err.to_string())?;
    let stamp = utc_stamp().replace([' ', ':', '+', '.'], "-");
    let target = dir.join(format!("master-{stamp}.db"));
    if target.exists() {
        return Err(format!("{} already exists", target.display()));
    }
    let staging = dir.join(format!(".staging-{stamp}"));
    rbl_core::durable::create_dir_all(&staging).map_err(|err| err.to_string())?;
    let staged = staging.join("master.db");
    conn.execute("VACUUM main INTO ?1", [staged.to_string_lossy().as_ref()])
        .map_err(|err| err.to_string())?;
    rbl_core::durable::replace(&staged, &target).map_err(|err| err.to_string())?;
    let _ = std::fs::remove_dir_all(&staging);
    prune_backups(&dir);
    Ok(target)
}

fn prune_backups(dir: &Path) {
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with("master-") && name.ends_with(".db"))
        })
        .collect();
    files.sort();
    let keep = 5;
    if files.len() > keep {
        for path in &files[..files.len() - keep] {
            let _ = std::fs::remove_file(path);
        }
    }
}

fn utc_stamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    let days = (secs / 86_400) as i64;
    let tod = secs % 86_400;
    let (year, month, day) = civil_from_days(days);
    let hour = tod / 3600;
    let minute = (tod % 3600) / 60;
    let second = tod % 60;
    format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}+00:00")
}

/// Howard Hinnant's civil-from-days, days since 1970-01-01.
fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { y + 1 } else { y };
    (year as i32, month as u32, day as u32)
}

fn rekordbox_app_is_running() -> bool {
    let Ok(output) = Command::new("ps").args(["-ax", "-o", "comm="]).output() else {
        return false;
    };
    let text = String::from_utf8_lossy(&output.stdout);
    text.lines()
        .any(|line| line.trim_end().ends_with("/rekordbox.app/Contents/MacOS/rekordbox"))
}
