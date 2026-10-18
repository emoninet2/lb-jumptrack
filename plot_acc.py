"""Download or load hex ACC and export an app-derived scalar g chart, CSV and JSON."""

import argparse
import asyncio
import json
from pathlib import Path

from acc_decoder import acc_csv, decode_acc
from jumptrack_cli import bounded


async def download(args):
    from bleak.exc import BleakError

    from jumptrack import ADDRESS, JumpTrack

    device = JumpTrack(address=args.address or ADDRESS)
    try:
        await device.connect()
        return await device.get_acc(
            args.jump, args.start, args.duration, hex_format=True, timeout=args.timeout
        )
    except BleakError as exc:
        raise ConnectionError(str(exc)) from exc
    finally:
        await device.disconnect()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--jump", type=bounded(-2147483648, 2147483647))
    parser.add_argument("--start", type=bounded(0, 2147483647))
    parser.add_argument("--duration", type=bounded(1, 2147483647))
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=bounded(1, 3600), default=90)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("jumptrack_data/acc_plots")
    )
    args = parser.parse_args(argv)
    if args.jump is not None and (args.start is None or args.duration is None):
        parser.error("--jump requires --start and --duration")
    if args.file is not None and (
        args.address or args.start is not None or args.duration is not None
    ):
        parser.error(
            "--file uses the saved response parameters; omit --address, --start and --duration"
        )
    try:
        raw = (
            args.file.read_text(encoding="utf-8")
            if args.file
            else asyncio.run(download(args))
        )
        expected = (
            (args.jump, args.start, args.duration) if args.jump is not None else None
        )
        decoded = decode_acc(raw, expected=expected)
        if not decoded["samples"]:
            print(
                "Device returned no ACC samples. No chart or samples were fabricated."
            )
            return
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        prefix = (
            args.output_dir
            / f"jump_{decoded['jump_number']:05d}_acc_{decoded['start_time_seconds']}_{decoded['requested_duration_seconds']}"
        )
        paths = {
            suffix: prefix.with_suffix(suffix)
            for suffix in (".txt", ".json", ".csv", ".png")
        }
        if args.file is not None and args.file.resolve() in {
            p.resolve() for p in paths.values()
        }:
            raise ValueError(
                "Outputs would overwrite the source response; choose another --output-dir"
            )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        paths[".txt"].write_text(raw, encoding="utf-8")
        paths[".json"].write_text(
            json.dumps(decoded, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        paths[".csv"].write_text(acc_csv(decoded) + "\n", encoding="utf-8")
        with plt.rc_context({"axes.spines.top": False, "axes.spines.right": False}):
            fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
            ax.plot(
                [s["time_seconds"] for s in decoded["samples"]],
                [s["acceleration_g"] for s in decoded["samples"]],
            )
            ax.set(
                xlabel="Time (seconds)",
                ylabel="Acceleration (g; app scalar)",
                title=f"Jump {decoded['jump_number']} — ACC",
            )
            ax.grid(alpha=0.2)
            fig.savefig(paths[".png"], dpi=180)
            plt.close(fig)
        print(
            f"{decoded['sample_count']} ACC samples; checksum verified\nChart: {paths['.png'].resolve()}"
        )
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
