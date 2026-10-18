"""Read and plot JumpTrack profiles with app-derived altitude and vertical speed.

Offline: .venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt
Live:    .venv/bin/python plot_profile.py --jump 35

Default decoding follows JumpTrack Android 1.1.64. CRC and byte-count metadata are verified.
Use --raw for raw words or explicit pressure options for the older experimental model.
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from profile_decoder import (
    decode_profile,
    format_profile_summary,
    parse_profile,
    profile_csv,
)


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


def save_plot(
    profile, destination, sample_interval=None, show=False, converted=None, decoded=None
):
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    words = profile["raw_words"]
    x = list(range(len(words)))
    label = "Sample index (sampling interval unknown)"
    if decoded:
        x = [sample["time_seconds"] for sample in decoded["samples"]]
        label = "Time (seconds; JumpTrack chart origin)"
    elif sample_interval is not None:
        x = [i * sample_interval for i in x]
        label = f"Elapsed seconds (user-supplied interval: {sample_interval:g} s)"
    with plt.rc_context(
        {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
    ):
        fig, axes = plt.subplots(
            3 if converted or decoded else 1,
            1,
            figsize=(11, 10 if converted or decoded else 5.5),
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
        if decoded:
            axes[1].plot(
                x, [v["altitude"] for v in decoded["samples"]], color="#13866c"
            )
            axes[1].axhline(
                decoded["summary"]["deployment_altitude"],
                color="#8a4f9e",
                linestyle="--",
                label="Recorded deployment altitude",
            )
            axes[1].legend()
            axes[1].set_ylabel(f"Altitude ({decoded['altitude_unit']})")
            available = [
                v for v in decoded["samples"] if v["vertical_speed"] is not None
            ]
            axes[2].plot(
                [v["time_seconds"] for v in available],
                [v["vertical_speed"] for v in available],
                color="#a46118",
            )
            axes[2].set_ylabel(f"Vertical speed ({decoded['speed_unit']})")
            axes[2].set_title(
                "Positive descent; app-derived 3/6-second speed windows",
                loc="left",
                fontsize=10,
            )
        elif converted:
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
            f"{len(words):,} words • {'JumpTrack 1.1.64 decoder' if decoded else 'experimental interpretation'} • checksum verified",
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
        "--file", type=Path, help="Use a saved profile without Bluetooth"
    )
    source.add_argument("--jump", type=int, help="Download one profile (read-only)")
    parser.add_argument("--address", help="BLE identifier for live reads")
    parser.add_argument("--timeout", type=positive_float, default=90)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("jumptrack_data/profile_plots")
    )
    parser.add_argument(
        "--units", choices=("feet", "meters"), help="Altitude units (app default: feet)"
    )
    parser.add_argument(
        "--speed-unit", choices=("mph", "kmh", "fps", "mps"), default="mph"
    )
    parser.add_argument(
        "--raw", action="store_true", help="Plot raw words without app decoding"
    )
    parser.add_argument(
        "--sample-interval",
        type=positive_float,
        help="Override timing for raw/experimental plots only",
    )
    parser.add_argument(
        "--pressure-scale",
        type=positive_float,
        help="Select legacy experimental pressure model with this hPa/count scale",
    )
    parser.add_argument(
        "--reference-pressure",
        type=positive_float,
        help="Reference hPa for legacy experimental model",
    )
    parser.add_argument("--strict-count", action="store_true")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)
    if args.expected_count is not None and args.expected_count < 0:
        parser.error("--expected-count must be nonnegative")
    if args.jump is not None and not -2147483648 <= args.jump <= 2147483647:
        parser.error("--jump must fit a signed Java int")
    experimental = args.pressure_scale is not None
    if experimental != (args.reference_pressure is not None):
        parser.error(
            "--pressure-scale and --reference-pressure must be supplied together"
        )
    if args.raw and (experimental or args.units is not None):
        parser.error("--raw cannot be combined with pressure conversion or --units")
    if args.sample_interval is not None and not (args.raw or experimental):
        parser.error(
            "App decoding uses 0.25-second timing; --sample-interval applies only to --raw or experimental conversion"
        )
    if args.file is not None and args.address:
        parser.error("--address applies only to --jump")
    try:
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
            print("WARNING: " + warning, file=sys.stderr)
        converted = None
        decoded = None
        if experimental:
            converted = convert_profile(
                profile,
                pressure_scale_hpa=args.pressure_scale,
                reference_pressure_hpa=args.reference_pressure,
                altitude_unit=args.units or "meters",
            )
        elif not args.raw:
            decoded = decode_profile(
                profile, altitude_unit=args.units or "feet", speed_unit=args.speed_unit
            )
        directory = args.output_dir
        prefix = directory / f"jump_{profile['jump_number']:05d}"
        tag = (
            "_" + decoded["altitude_unit"] + "_" + decoded["speed_unit"]
            if decoded
            else "_estimated_" + converted["altitude_unit"]
            if converted
            else ""
        )
        raw_path = prefix.with_name(prefix.name + "_profile.txt")
        csv_path = prefix.with_name(prefix.name + tag + "_samples.csv")
        metadata_path = prefix.with_name(prefix.name + tag + "_metadata.json")
        plot_path = prefix.with_name(prefix.name + tag + ".png")
        if args.file is not None and args.file.resolve() in {
            p.resolve() for p in (csv_path, metadata_path, plot_path)
        }:
            raise ValueError(
                "Output would overwrite the source profile; choose another --output-dir"
            )
        directory.mkdir(parents=True, exist_ok=True)
        if args.file is None or raw_path.resolve() != args.file.resolve():
            raw_path.write_text(raw, encoding="utf-8")
        metadata = {key: value for key, value in profile.items() if key != "raw_words"}
        metadata["sample_interval_seconds"] = 0.25 if decoded else args.sample_interval
        if decoded:
            csv_path.write_text(profile_csv(decoded) + "\n", encoding="utf-8")
            metadata["decoded"] = {
                key: value for key, value in decoded.items() if key != "samples"
            }
        else:
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                columns = ["sample_index", "raw_value", "hex_word"]
                if args.sample_interval is not None:
                    columns.append("elapsed_seconds")
                if converted:
                    columns.extend(
                        [
                            "assumed_pressure_hpa",
                            "estimated_height_m",
                            "estimated_height_" + converted["altitude_unit"],
                        ]
                    )
                writer.writerow(columns)
                for index, value in enumerate(profile["raw_words"]):
                    row = [index, value, f"{value:04X}"]
                    if args.sample_interval is not None:
                        row.append(index * args.sample_interval)
                    if converted:
                        row.extend(
                            [
                                converted["pressure_hpa"][index],
                                converted["estimated_height_m"][index],
                                converted["estimated_height"][index],
                            ]
                        )
                    writer.writerow(row)
            if converted:
                metadata["conversion"] = {
                    key: value
                    for key, value in converted.items()
                    if key
                    not in ("pressure_hpa", "estimated_height_m", "estimated_height")
                }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        save_plot(
            profile, plot_path, args.sample_interval, args.show, converted, decoded
        )
        if decoded:
            print(format_profile_summary(decoded))
        else:
            print(
                f"Jump {profile['jump_number']}: {len(profile['raw_words'])} raw words; checksum verified"
            )
        print(
            f"Plot: {plot_path.resolve()}\nCSV: {csv_path.resolve()}\nMetadata: {metadata_path.resolve()}"
        )
    except ImportError as exc:
        parser.exit(1, f"Install plotting dependencies from requirements.txt: {exc}\n")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
