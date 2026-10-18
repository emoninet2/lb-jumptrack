"""Read one JumpTrack hex profile and plot raw words or an explicitly assumed pressure interpretation.

Offline: .venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt
Live:    .venv/bin/python plot_profile.py --jump 35

This is a manual read-only test, not an automatic Bluetooth unit test.
The observed layout and pressure interpretation are experimental. Unit conversion
requires an explicit scale and reference pressure; neither comes from the Java master.
"""

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path


def parse_profile(raw, *, expected_profile_count=None, strict_count=False):
    """Parse the layout observed in the saved PROTRACK 3 firmware 01.04 reply.

    Observed layout: command echo, 16 decimal header lines, then hex words,
    checksum metadata, EOF. Preserve header fields without assigning meanings.
    No checksum verification is performed.
    """
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines or not re.fullmatch(r"Get Hex Profile in Jump -?[0-9]+", lines[0]):
        raise ValueError("Expected a Get Hex Profile in Jump response")
    if lines[-1] != "EOF":
        raise ValueError("Incomplete profile response: missing final EOF")
    checksum_start = next(
        (i for i, line in enumerate(lines) if line.startswith("CheckSum.")), None
    )
    if checksum_start is None:
        raise ValueError("Missing checksum metadata boundary")
    header = lines[1:17]
    if len(header) != 16 or any(not re.fullmatch(r"[0-9]+", field) for field in header):
        raise ValueError("Unrecognized profile header: expected 16 decimal fields")
    requested_jump = int(lines[0].split()[-1])
    if int(header[0]) != requested_jump:
        raise ValueError("Echoed jump number does not match the profile header")
    payload_lines = lines[17:checksum_start]
    if not payload_lines:
        raise ValueError("Profile contains no hex data")
    if any(not re.fullmatch(r"(?:[0-9A-Fa-f]{4})+", line) for line in payload_lines):
        raise ValueError("Malformed hex payload: expected groups of four hex digits")
    encoded = "".join(payload_lines)
    words = [int(encoded[i : i + 4], 16) for i in range(0, len(encoded), 4)]
    declared_count = int(header[-1])
    decoded_count = len(words)
    warnings = []
    matches_observed = declared_count == decoded_count + 1
    if not matches_observed:
        warnings.append(
            f"Profile count mismatch: header={declared_count}, decoded={decoded_count}; "
            "observed firmware layout expects header = decoded + 1. "
            "Possible missing/extra data or a different profile layout."
        )
    if expected_profile_count is not None:
        if (
            isinstance(expected_profile_count, bool)
            or not isinstance(expected_profile_count, int)
            or expected_profile_count < 0
        ):
            raise ValueError("expected_profile_count must be a nonnegative integer")
        if expected_profile_count != declared_count:
            warnings.append(
                f"Jump-list/header count mismatch: list={expected_profile_count}, header={declared_count}"
            )
    if strict_count and warnings:
        raise ValueError("; ".join(warnings))
    return {
        "profile_count_field": declared_count,
        "decoded_word_count": decoded_count,
        "count_difference": declared_count - decoded_count,
        "count_matches_observed_layout": matches_observed,
        "expected_profile_count": expected_profile_count,
        "validation_warnings": warnings,
        "jump_number": requested_jump,
        "header_decimal_fields": [int(field) for field in header],
        "raw_words": words,
        "checksum_metadata": lines[checksum_start:-1],
        "interpretation": "Experimental 16-bit hex words as printed; units and sample period unknown",
    }


async def download_profile(jump, address, timeout):
    # Keep Bleak optional when plotting a saved file.
    from jumptrack import ADDRESS, JumpTrack

    device = JumpTrack(address=address or ADDRESS)  # Writes disabled by default.
    try:
        await device.connect()
        return await device.get_jump_profile_hex(jump, timeout=timeout)
    finally:
        await device.disconnect()


def convert_profile(
    profile, *, pressure_scale_hpa, reference_pressure_hpa, altitude_unit="meters"
):
    """Experimental pressure/height interpretation; never changes raw words.

    pressure_hpa = raw_word * pressure_scale_hpa (USER ASSUMPTION).
    Relative height is NASA's troposphere curve-fit altitude at sample pressure
    minus its altitude at reference pressure. It is an estimate, not verified
    device altitude or actual AGL. Source and full equation are in docs/PROFILE_FORMAT.md.
    """
    import math

    for name, value in [
        ("pressure_scale_hpa", pressure_scale_hpa),
        ("reference_pressure_hpa", reference_pressure_hpa),
    ]:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{name} must be finite and positive")
    if altitude_unit not in ("meters", "feet"):
        raise ValueError("altitude_unit must be meters or feet")
    pressures = [word * pressure_scale_hpa for word in profile["raw_words"]]
    if any(not math.isfinite(pressure) or pressure <= 0 for pressure in pressures):
        raise ValueError("Pressure must be finite and positive")

    # NASA equation uses kPa; 10 hPa = 1 kPa. Avoid opaque preset constants.
    def model_height(pressure_hpa):
        return (
            288.14 - 288.08 * ((pressure_hpa / 10) / 101.29) ** (1 / 5.256)
        ) / 0.00649

    reference_height = model_height(reference_pressure_hpa)
    model_heights = [model_height(pressure) for pressure in pressures]
    if any(height > 11000 for height in [reference_height, *model_heights]):
        raise ValueError(
            "Outside the troposphere model: pressure implies height above 11 km"
        )
    heights_m = [height - reference_height for height in model_heights]
    return {
        "pressure_hpa": pressures,
        "estimated_height_m": heights_m,
        "estimated_height": [
            height / 0.3048 if altitude_unit == "feet" else height
            for height in heights_m
        ],
        "altitude_unit": altitude_unit,
        "pressure_scale_hpa_per_count": pressure_scale_hpa,
        "reference_pressure_hpa": reference_pressure_hpa,
        "source": "https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html",
        "status": "ASSUMED encoding; pressure-derived height relative to reference, not verified device altitude or AGL",
    }


def save_plot(profile, destination, sample_interval=None, show=False, converted=None):
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    words = profile["raw_words"]
    x = list(range(len(words)))
    label = "Sample index (sampling interval unknown)"
    if sample_interval is not None:
        x = [i * sample_interval for i in x]
        label = f"Elapsed seconds (user-supplied interval: {sample_interval:g} s)"
    with plt.rc_context(
        {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
    ):
        fig, axes = plt.subplots(
            3 if converted else 1,
            1,
            figsize=(11, 10 if converted else 5.5),
            sharex=True,
            layout="constrained",
            squeeze=False,
        )
        axes = [row[0] for row in axes]
        axes[0].plot(x, words, color="#157a9e", linewidth=1.6)
        axes[0].set_title(
            f"Jump {profile['jump_number']} — raw profile", loc="left", weight="bold"
        )
        axes[0].set_ylabel("Raw 16-bit value")
        if converted:
            axes[1].plot(x, converted["pressure_hpa"], color="#a46118", linewidth=1.6)
            axes[1].set_ylabel("Assumed pressure (hPa)")
            axes[1].set_title(
                f"ASSUMPTION: {converted['pressure_scale_hpa_per_count']:g} hPa per raw count",
                loc="left",
                fontsize=10,
            )
            axes[2].plot(
                x, converted["estimated_height"], color="#13866c", linewidth=1.6
            )
            axes[2].set_ylabel(f"Estimated height ({converted['altitude_unit']})")
            axes[2].set_title(
                f"Relative to {converted['reference_pressure_hpa']:g} hPa; encoding unverified",
                loc="left",
                fontsize=10,
            )
            axes[2].axhline(0, color="#555555", linewidth=0.7, linestyle="--")
        else:
            axes[0].set_ylabel("Raw 16-bit value (units unverified)")
        axes[-1].set_xlabel(label)
        for ax in axes:
            ax.grid(alpha=0.2)
        fig.suptitle(
            f"{len(words):,} words • experimental decoding • checksum not verified",
            fontsize=10,
            color="#555555",
        )
        fig.savefig(destination, dpi=180)
        if show:
            plt.show()
        plt.close(fig)


def positive_float(value):
    import math

    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected a finite value greater than zero")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--file",
        type=Path,
        help="Use a previously downloaded text profile; no Bluetooth",
    )
    source.add_argument(
        "--jump", type=int, help="Download this one jump profile (read-only)"
    )
    parser.add_argument("--address", help="Override BLE address for live reads")
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=90,
        help="Live response timeout in seconds (default: 90)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("jumptrack_data/profile_plots")
    )
    parser.add_argument(
        "--sample-interval",
        type=positive_float,
        help="Known seconds between samples; otherwise use sample index",
    )
    parser.add_argument(
        "--pressure-scale",
        type=positive_float,
        help="EXPERIMENTAL assumed hPa per raw count (e.g. 0.1)",
    )
    parser.add_argument(
        "--reference-pressure",
        type=positive_float,
        help="EXPERIMENTAL reference pressure in hPa (required with --pressure-scale)",
    )
    parser.add_argument(
        "--units",
        choices=("meters", "feet"),
        help="Estimated height unit (requires both pressure options)",
    )
    parser.add_argument(
        "--strict-count",
        action="store_true",
        help="Refuse profiles with count mismatches instead of warning",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        help="Optional count field from the jump list; compare against profile header",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Also display an interactive plot window if a GUI backend is available",
    )
    args = parser.parse_args(argv)
    if args.expected_count is not None and args.expected_count < 0:
        parser.error("--expected-count must be nonnegative")
    if args.jump is not None and not -2147483648 <= args.jump <= 2147483647:
        parser.error("--jump must fit a signed Java int")
    if (args.pressure_scale is None) != (args.reference_pressure is None):
        parser.error(
            "--pressure-scale and --reference-pressure must be supplied together"
        )
    if args.units is not None and args.pressure_scale is None:
        parser.error(
            "--units requires explicit --pressure-scale and --reference-pressure assumptions"
        )
    if args.file is not None and args.address:
        parser.error("--address applies only to --jump")
    try:
        import importlib.util

        if importlib.util.find_spec("matplotlib") is None:
            parser.error(
                "Install plotting dependency: .venv/bin/python -m pip install matplotlib"
            )
        raw = (
            args.file.read_text(encoding="utf-8")
            if args.file is not None
            else asyncio.run(download_profile(args.jump, args.address, args.timeout))
        )
        profile = parse_profile(
            raw,
            expected_profile_count=args.expected_count,
            strict_count=args.strict_count,
        )
        for warning in profile["validation_warnings"]:
            print(f"WARNING: {warning}", file=sys.stderr)
        converted = None
        if args.pressure_scale is not None:
            converted = convert_profile(
                profile,
                pressure_scale_hpa=args.pressure_scale,
                reference_pressure_hpa=args.reference_pressure,
                altitude_unit=args.units or "meters",
            )
        directory = args.output_dir
        directory.mkdir(parents=True, exist_ok=True)
        prefix = directory / f"jump_{profile['jump_number']:05d}"
        raw_path = prefix.with_name(prefix.name + "_profile.txt")
        # Never rewrite the input file when output and source happen to match.
        if args.file is None or raw_path.resolve() != args.file.resolve():
            raw_path.write_text(raw, encoding="utf-8")
        tag = "_estimated_" + converted["altitude_unit"] if converted else ""
        csv_path = prefix.with_name(prefix.name + tag + "_samples.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["sample_index", "raw_value", "hex_word"]
                + (["elapsed_seconds"] if args.sample_interval is not None else [])
                + (
                    [
                        "assumed_pressure_hpa",
                        "estimated_height_m",
                        "estimated_height_" + converted["altitude_unit"],
                    ]
                    if converted
                    else []
                )
            )
            for i, value in enumerate(profile["raw_words"]):
                writer.writerow(
                    [i, value, f"{value:04X}"]
                    + (
                        [i * args.sample_interval]
                        if args.sample_interval is not None
                        else []
                    )
                    + (
                        [
                            converted["pressure_hpa"][i],
                            converted["estimated_height_m"][i],
                            converted["estimated_height"][i],
                        ]
                        if converted
                        else []
                    )
                )
        metadata = {key: value for key, value in profile.items() if key != "raw_words"}
        metadata.update(
            word_count=len(profile["raw_words"]),
            sample_interval_seconds=args.sample_interval,
        )
        if converted:
            metadata["conversion"] = {
                key: value
                for key, value in converted.items()
                if key not in ("pressure_hpa", "estimated_height_m", "estimated_height")
            }
        prefix.with_name(prefix.name + tag + "_metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        plot_path = prefix.with_name(prefix.name + tag + ".png")
        save_plot(profile, plot_path, args.sample_interval, args.show, converted)
        print(f"Jump {profile['jump_number']}: {len(profile['raw_words'])} raw words")
        print(
            f"Profile count field: {profile['profile_count_field']}; decoded + 1 check: "
            f"{'PASS' if profile['count_matches_observed_layout'] else 'MISMATCH'}"
        )
        print(
            "Sample period and encoding are unverified; raw data and assumptions are preserved."
        )
        if converted:
            print(
                f"EXPERIMENTAL estimated height: {converted['estimated_height'][0]:.1f} -> {converted['estimated_height'][-1]:.1f} {converted['altitude_unit']}"
            )
        print(f"Plot: {plot_path.resolve()}\nCSV:  {csv_path.resolve()}")
    except (OSError, ValueError, TimeoutError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
