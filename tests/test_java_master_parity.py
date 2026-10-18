"""Execute extracted master method bodies as an independent Java oracle.

Never changes UARTCommandBuilder.java. Only generated copies under a temporary
folder are compiled. Android/Kotlin helpers are replaced with small type/runtime
stubs; the sole method-body compilation repair is decompiler Iterator<T> ->
Iterator<?>. This checks command logic, not Android library behavior or firmware.
"""

import base64
import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from datetime import datetime
from enum import Enum
from pathlib import Path

import java_uart_command_builder as port

MASTER = Path(__file__).resolve().parents[1] / "UARTCommandBuilder.java"
MASTER_SHA256 = "b68c90a5d30d2dc536a352fcb8c584f83fb4117519c6d0d2fac4a597358e76f5"


def block(source, start):
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


def master_methods():
    if not MASTER.exists():
        import json

        signatures = json.loads(
            (Path(__file__).parent / "fixtures/java_master_signatures.json").read_text()
        )
        return [(name, parameters, "") for name, parameters in signatures]
    source = MASTER.read_text()
    methods = []
    for match in re.finditer(r"public final String (\w+)\(([^)]*)\)", source):
        parameters = (
            [item.strip().rsplit(" ", 1) for item in match.group(2).split(",")]
            if match.group(2)
            else []
        )
        methods.append((match.group(1), parameters, block(source, match.start())))
    return methods


def cases():
    samples = {
        "hours": 12,
        "minutes": 3,
        "seconds": 4,
        "bank": 2,
        "pitch": 4,
        "volume": 7,
        "backlightValue": 50,
        "lcdTimeOut": 30,
        "countdown": 5,
        "sensitivity": 12,
        "bankIndex": 2,
        "sign": -1,
        "count": 35,
        "jumpNumberArg": 35,
        "startTime": 5,
        "durationArg": 90,
        "jumpNumber": 35,
        "altitude": 65000,
    }
    result = []
    for name, parameters, _ in master_methods():
        args = []
        for kind, param in parameters:
            if kind == "Calendar":
                value = datetime(2026, 10, 18, 14, 7, 9)
            elif kind == "List<String>":
                value = ["1000", "2000", "3000"]
            elif kind == "String":
                value = str(samples[param.removesuffix("String")])
            elif kind == "boolean":
                value = True
            elif kind in ("int", "long"):
                value = samples[param]
            else:
                value = next(iter(getattr(port, kind)))
            args.append(value)
        result.append((name, parameters, args))
        for index, (kind, param) in enumerate(parameters):
            if kind in ("int", "long"):
                variants = [
                    -2147483648,
                    -1,
                    0,
                    1,
                    4,
                    5,
                    7,
                    8,
                    10,
                    11,
                    999,
                    1000,
                    65000,
                    65001,
                    99999,
                    100000,
                    2147483647,
                ]
                if kind == "long":
                    variants += [-9223372036854775808, 9223372036854775807]
            elif kind == "List<String>":
                variants = [
                    [],
                    ["1", "2"],
                    ["1", "2", "3"],
                    ["1", "2", "3", "4"],
                    ["1", "2", "3", "4", "5"],
                    ["1", "2", "3", "999999999999", "5"],
                    ["1", "2", "3", "bad", "5"],
                    ["1", "2", "2147483648"],
                    ["1", "2", ""],
                    ["1", "2", "-3"],
                    ["1", "2", None],
                    ["١", "٢", "٣"],
                    ["𝟙", "2", "3"],
                    None,
                ]
            elif kind == "String":
                variants = [
                    "+001",
                    "-1",
                    "2147483647",
                    "-2147483648",
                    "2147483648",
                    "",
                    " 1",
                    "1 ",
                    "١٢",
                    "𝟙",
                ]
            elif kind == "boolean":
                variants = [False]
            elif kind == "Calendar":
                variants = [
                    datetime(2000, 2, 29, 0, 0, 0),
                    datetime(2026, 12, 31, 23, 59, 59),
                ]
            else:
                variants = list(getattr(port, kind))
            for value in variants:
                altered = args.copy()
                altered[index] = value
                result.append((name, parameters, altered))
    return result


def java_value(value, kind):
    import json

    if value is None:
        return "null"
    if isinstance(value, datetime):
        return f"calendar({value.year},{value.month},{value.day},{value.hour},{value.minute},{value.second})"
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return (
            "Arrays.asList("
            + ",".join(java_value(item, "String") for item in value)
            + ")"
        )
    return str(value) + ("L" if kind == "long" else "")


STUBS = """
class TimeModel { static final String ZERO_LEADING_NUMBER_FORMAT="%02d"; }
class Intrinsics {
 static void checkNotNullParameter(Object o,String label) { if(o==null) throw new NullPointerException(label); }
 static void checkNotNullExpressionValue(Object o,String label) { if(o==null) throw new NullPointerException(label); }
}
class StringCompanionObject { static final StringCompanionObject INSTANCE=new StringCompanionObject(); }
class CrashlyticsWrapper { static final CrashlyticsWrapper INSTANCE=new CrashlyticsWrapper(); void logError(String s) {} }
class StringUtils {
 static final String SPACE=" ";
 static boolean isNumeric(String s) { if(s==null || s.length()==0) return false; for(int i=0;i<s.length();i++) if(!Character.isDigit(s.charAt(i))) return false; return true; }
}
class NoWhenBranchMatchedException extends RuntimeException {}
"""


def oracle_source(testcases):
    source = MASTER.read_text()
    mapping_start = source.index(
        "public static final /* synthetic */ class WhenMappings"
    )
    mapping = block(source, mapping_start)
    helper_start = source.index("private final boolean isAllNumeric")
    helper = block(source, helper_start).replace("Iterator<T>", "Iterator<?>")
    methods = "\n".join(body for _, _, body in master_methods())
    enums = "\n".join(
        "enum "
        + name
        + " {"
        + ",".join(member.name for member in getattr(port, name))
        + "}"
        for name in (
            "DistanceUOM",
            "SpeedUOM",
            "DeviceBLEMode",
            "DeviceDiveType",
            "DeviceTemperatureUnits",
            "DateFormat",
        )
    )
    consts = "\n".join(
        re.findall(r"public static final (?:String|int) \w+ = [^;]+;", source)
    )
    calls = []
    for name, parameters, args in testcases:
        text = ",".join(
            java_value(value, kind) for value, (kind, _) in zip(args, parameters)
        )
        calls.append(f"emit(() -> builder.{name}({text}));")
    # Split runner methods to stay below Java's per-method bytecode limit.
    chunks = [calls[i : i + 80] for i in range(0, len(calls), 80)]
    runners = "\n".join(
        f"static void run{i}(UARTCommandBuilder builder) {{" + "\n".join(chunk) + "}"
        for i, chunk in enumerate(chunks)
    )
    run = "".join(f"run{i}(builder);" for i in range(len(chunks)))
    return (
        """import java.util.*;
import java.nio.charset.StandardCharsets;
"""
        + enums
        + STUBS
        + "\nclass UARTCommandBuilder {\n"
        + consts
        + "\n"
        + mapping
        + "\n"
        + methods
        + "\n"
        + helper
        + """
}
public class Oracle {
 interface Call { String run(); }
 static Calendar calendar(int y,int m,int d,int h,int min,int s) { Calendar c=new GregorianCalendar(); c.clear(); c.set(y,m-1,d,h,min,s); return c; }
 static void emit(Call call) {
  try { String result=call.run(); System.out.println(result==null ? "NULL" : "OK:"+Base64.getEncoder().encodeToString(result.getBytes(StandardCharsets.UTF_8))); }
  catch(NullPointerException e) { System.out.println("ERROR:TypeError"); }
  catch(IllegalArgumentException e) { System.out.println("ERROR:ValueError"); }
 }
"""
        + runners
        + "\n public static void main(String[] args) { Locale.setDefault(Locale.US); UARTCommandBuilder builder=new UARTCommandBuilder();"
        + run
        + "}\n}"
    )


class MasterParityTests(unittest.TestCase):
    def test_saved_manifest_matches_port_without_private_source(self):
        import json

        manifest = json.loads(
            (MASTER.parent / "docs/java_master_manifest.json").read_text()
        )
        self.assertEqual(manifest["constants"], port.CONSTANTS)
        signatures = {
            name: [
                [
                    kind.__name__ if isinstance(kind, type) else kind
                    for kind in signature
                ]
                for signature in overloads
            ]
            for name, overloads in port.SIGNATURES.items()
        }
        self.assertEqual(manifest["signatures"], signatures)
        self.assertEqual(manifest["master_sha256"], MASTER_SHA256)
        self.assertEqual(
            Counter(name for name, _, _ in master_methods()),
            Counter(
                {name: len(overloads) for name, overloads in port.SIGNATURES.items()}
            ),
        )

    @unittest.skipUnless(MASTER.exists(), "Private Java reference is not distributed")
    def test_master_hash_and_complete_manifest(self):
        self.assertEqual(hashlib.sha256(MASTER.read_bytes()).hexdigest(), MASTER_SHA256)
        self.assertEqual(
            Counter(name for name, _, _ in master_methods()),
            Counter(
                {name: len(signatures) for name, signatures in port.SIGNATURES.items()}
            ),
        )
        for name in port.SIGNATURES:
            self.assertTrue(callable(getattr(port.JavaUARTCommandBuilder, name)))
        source = MASTER.read_text()
        for name, value in port.CONSTANTS.items():
            if name == "$stable":
                self.assertIn("public static final int $stable = 0;", source)
            else:
                literal = (
                    str(value)
                    if isinstance(value, int)
                    else '"' + value.replace("\\", "\\\\") + '"'
                )
                self.assertIn(f"{name} = {literal};", source)

    @unittest.skipUnless(
        MASTER.exists() and shutil.which("javac") and shutil.which("java"),
        "Java JDK required for master oracle",
    )
    def test_python_against_executed_master_bodies(self):
        testcases = cases()
        with tempfile.TemporaryDirectory(prefix="jumptrack-java-oracle-") as folder:
            path = Path(folder)
            (path / "Oracle.java").write_text(oracle_source(testcases))
            compiled = subprocess.run(
                ["javac", "-encoding", "UTF-8", "Oracle.java"],
                cwd=folder,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            ran = subprocess.run(
                ["java", "-cp", folder, "Oracle"],
                capture_output=True,
                text=True,
                check=True,
            )
        results = ran.stdout.splitlines()
        self.assertEqual(len(results), len(testcases))
        builder = port.JavaUARTCommandBuilder()
        # Error logs are the Python equivalent of Crashlytics.logError.
        with self.assertLogs(port.__name__, level="ERROR"):
            for (name, _, args), expected in zip(testcases, results):
                with self.subTest(method=name, args=args):
                    try:
                        value = getattr(builder, name)(*args)
                        actual = (
                            "NULL"
                            if value is None
                            else "OK:" + base64.b64encode(value.encode()).decode()
                        )
                    except (ValueError, TypeError) as exc:
                        actual = "ERROR:" + type(exc).__name__
                    self.assertEqual(actual, expected)
        print(f"Java master oracle: {len(testcases)} input cases matched.")


if __name__ == "__main__":
    unittest.main()
