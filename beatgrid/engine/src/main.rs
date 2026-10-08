//! Decode one file with rbl-audio and print the rbl-analysis beat grid.
//!
//! The Python command reads this JSON. Key detection runs inside
//! rbl-analysis and is not printed.

use std::env;
use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    let result = if args.first().is_some_and(|arg| arg == "--commit-rekordbox") {
        commit::commit_rekordbox()
    } else {
        run(args)
    };
    match result {
        Ok(json) => {
            println!("{json}");
            ExitCode::SUCCESS
        }
        Err(message) => {
            eprintln!("{message}");
            ExitCode::from(1)
        }
    }
}

mod commit;

fn run(args: Vec<String>) -> Result<String, String> {
    let mut args = args.into_iter();
    let mut min_bpm = 70.0_f64;
    let mut max_bpm = 180.0_f64;
    let mut file: Option<String> = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--min-bpm" => min_bpm = number(&mut args, "--min-bpm")?,
            "--max-bpm" => max_bpm = number(&mut args, "--max-bpm")?,
            "--help" => {
                return Ok(
                    "grid-analyse --min-bpm 70 --max-bpm 180 FILE\n\
                     prints bpm and a beats list of n, ms, bpm"
                        .to_string(),
                );
            }
            other if other.starts_with('-') => return Err(format!("unknown argument {other}")),
            other => {
                if file.is_some() {
                    return Err("pass one audio file".to_string());
                }
                file = Some(other.to_string());
            }
        }
    }
    if min_bpm <= 0.0 || max_bpm <= min_bpm {
        return Err("BPM range must be a positive span, low then high".to_string());
    }
    let Some(file) = file else {
        return Err("pass an audio file".to_string());
    };

    let audio = rbl_audio::decode_mono(Path::new(&file), None).map_err(|err| err.to_string())?;
    if audio.samples.is_empty() || audio.sample_rate == 0 {
        return Err("no audio samples".to_string());
    }
    let mut options = rbl_analysis::AnalysisPreset::Rbxport.options();
    options.tempo.min_bpm = min_bpm;
    options.tempo.max_bpm = max_bpm;
    let result = rbl_analysis::analyse_with(&audio.samples, audio.sample_rate, options);
    if result.tempo.beats.is_empty() {
        return Err("analysis returned no beats".to_string());
    }
    let beats: Vec<serde_json::Value> = result
        .tempo
        .beats
        .iter()
        .map(|beat| {
            serde_json::json!({
                "n": beat.beat_number,
                "ms": beat.time_ms,
                "bpm": f64::from(beat.tempo_x100) / 100.0,
            })
        })
        .collect();
    let bpm = if result.tempo.bpm > 0.0 {
        result.tempo.bpm
    } else {
        f64::from(result.tempo.beats[0].tempo_x100) / 100.0
    };
    Ok(serde_json::json!({ "bpm": bpm, "beats": beats }).to_string())
}

fn number(args: &mut impl Iterator<Item = String>, flag: &str) -> Result<f64, String> {
    let Some(raw) = args.next() else {
        return Err(format!("{flag} needs a number"));
    };
    raw.parse::<f64>()
        .map_err(|_| format!("{flag} needs a number"))
}
