"""Execute recovered checksum and ACC methods without distributing app sources."""

import binascii
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from acc_decoder import decode_acc
from tests.test_java_master_parity import block
from tests.test_profile_parser import seal

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "jumptrack_data/apk_reference/1.1.64/full/sources/com/lb/altimeter/android"
)


@unittest.skipUnless(
    (SOURCE / "utils/CheckSumUtils.java").exists()
    and shutil.which("javac")
    and shutil.which("java"),
    "Recovered app sources and JDK required",
)
class RecoveredIntegrityTests(unittest.TestCase):
    def test_crc_table_and_acc_decode_against_recovered_methods(self):
        checksum = (SOURCE / "utils/CheckSumUtils.java").read_text()
        jump = (SOURCE / "presentation/utils/JumpUtils.java").read_text()
        table = re.search(
            r"private static final short\[\] crc16Array = .*?;", checksum
        ).group()
        method = block(checksum, checksum.index("public final int calculateCheckSUM("))
        # Resolve Kotlin's decompiler-only unsigned-array accessor to its Java equivalent.
        method = method.replace(
            "UShortArray.get-Mh2AYeg(CheckSumUtils.crc16Array, (b ^ (i >> 8)) & 255)",
            "CheckSumUtils.crc16Array[(b ^ (i >> 8)) & 255]",
        )
        method = re.sub(
            r"UShortArray\.[\w-]+\(CheckSumUtils\.crc16Array, (\(b \^ \(\w+ >> 8\)\) & 255)\)",
            r"CheckSumUtils.crc16Array[\1]",
            method,
        ).replace("UShort.MAX_VALUE", "65535")
        acc = block(jump, jump.index("private final List<Long> decodeHexAcc("))
        acc = acc.replace("UShort.MAX_VALUE", "65535")
        java = (
            """import java.util.*;
        class Intrinsics {static void checkNotNullParameter(Object o,String n){} static void checkNotNull(Object o){} static void checkNotNullExpressionValue(Object o,String n){}}
        class CharsKt {static int checkRadix(int r){return r;}}
        class CollectionsKt {static List<Long> emptyList(){return Collections.emptyList();}}
        class CrashlyticsWrapper {static final CrashlyticsWrapper INSTANCE=new CrashlyticsWrapper(); void logError(String s){} void logError(String s,Throwable t){}}
        class CheckSumUtils {"""
            + table
            + method
            + "}"
        )
        java += (
            "public class IntegrityOracle {"
            + acc
            + """public static void main(String[] args) {
          CheckSumUtils c=new CheckSumUtils();
          for(int length=0;length<256;length++){byte[] b=new byte[length]; for(int i=0;i<length;i++) b[i]=(byte)(i*37+length);System.out.println("CRC,"+length+","+c.calculateCheckSUM(b));}
          StringBuilder hex=new StringBuilder();for(int i=0;i<256;i++)hex.append(String.format("%04X",i*257));
          for(long value:new IntegrityOracle().decodeHexAcc(hex.toString())) System.out.println("ACC,"+value);
        }}"""
        )
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "IntegrityOracle.java").write_text(java)
            compiled = subprocess.run(
                ["javac", "IntegrityOracle.java"],
                cwd=folder,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(
                ["java", "-cp", folder, "IntegrityOracle"],
                capture_output=True,
                text=True,
                check=True,
            )
        lines = result.stdout.splitlines()
        for line in lines[:256]:
            _, length, crc = line.split(",")
            length = int(length)
            payload = bytes((i * 37 + length) & 255 for i in range(length))
            self.assertEqual(binascii.crc_hqx(payload, 0), int(crc))
        raw = seal(
            "Get Hex xACC 00033 000 060\r\n"
            + "".join(f"{i * 257:04X}" for i in range(256))
            + "\r\n"
        )
        actual = decode_acc(raw)["samples"]
        self.assertEqual(
            [s["acceleration_g"] for s in actual],
            [int(line.split(",")[1]) / 256 for line in lines[256:]],
        )
