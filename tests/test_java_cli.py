"""Original-name CLI/API parity tests, without a device connection."""
import base64
import contextlib
from datetime import datetime
from enum import Enum
import io
import json
import unittest
from unittest.mock import AsyncMock, patch

import jumptrack
import java_uart_command_builder as master
from jumptrack_cli import operation, preview
from tests.test_java_master_parity import cases, master_methods
from uart_command_builder import UARTCommandBuilder


def json_value(value):
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class JavaCLITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.parser = jumptrack.build_parser()

    def test_every_original_signature_has_json_cli_and_api(self):
        seen = set()
        for method, parameters, args in cases():
            key = (method, tuple(kind for kind, _ in parameters))
            if key in seen:
                continue
            seen.add(key)
            argv = ['java', method, json.dumps([json_value(value) for value in args])]
            op = operation(self.parser.parse_args(argv))
            self.assertEqual(preview(op, UARTCommandBuilder()), getattr(UARTCommandBuilder(), method)(*args))
            self.assertTrue(callable(getattr(jumptrack.JumpTrack,method)))
        self.assertEqual(len(seen),40)

    def test_json_cli_matches_all_663_master_inputs(self):
        builder = UARTCommandBuilder()
        with self.assertLogs('java_uart_command_builder', level='ERROR'):
            for method, _, args in cases():
                with self.subTest(method=method, args=args):
                    try:
                        expected = getattr(builder, method)(*args)
                        error = None
                    except (TypeError, ValueError) as exc:
                        error = type(exc)
                    parsed = self.parser.parse_args(['java', method, json.dumps([json_value(value) for value in args])])
                    if error:
                        with self.assertRaises((ValueError, TypeError)):
                            preview(operation(parsed), builder)
                    else:
                        self.assertEqual(preview(operation(parsed), builder), expected)

    async def test_original_cli_dry_run_for_all_signatures(self):
        seen=set()
        with patch.object(jumptrack,'BleakClient') as ble:
            for method, parameters, args in cases():
                key=(method,tuple(kind for kind,_ in parameters))
                if key in seen:
                    continue
                seen.add(key)
                output=io.StringIO()
                with contextlib.redirect_stdout(output):
                    await jumptrack.main(['--dry-run','java',method,json.dumps([json_value(value) for value in args])])
                self.assertEqual(output.getvalue().strip(),getattr(UARTCommandBuilder(),method)(*args))
            ble.assert_not_called()

    async def test_direct_transport_classifies_every_method(self):
        seen=set()
        with patch.object(jumptrack,'BleakClient'):
            device=jumptrack.JumpTrack(address="test-device", allow_writes=True,allow_destructive=True)
        device.send_command=AsyncMock(return_value='EOF\r\n')
        for method, parameters, args in cases():
            key=(method,tuple(kind for kind,_ in parameters))
            if key in seen:
                continue
            seen.add(key)
            await getattr(device,method)(*args,timeout=42)
            sent=device.send_command.call_args
            self.assertEqual(sent.args[0],getattr(device.commands,method)(*args))
            self.assertEqual(sent.kwargs,dict(timeout=42,write=method not in master.READ_METHODS and method not in master.DESTRUCTIVE_METHODS,destructive=method in master.DESTRUCTIVE_METHODS))

    async def test_null_never_constructs_a_ble_client_or_sends(self):
        argv=['java','prepareSendFreeFallSoundSetupCommand','[0,1]']
        with patch.object(jumptrack,'BleakClient') as ble:
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                await jumptrack.main(['--dry-run',*argv])
            self.assertEqual(output.getvalue().strip(),'null')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                await jumptrack.main(argv)
            self.assertEqual(exc.exception.code,2)
            ble.assert_not_called()
            device=jumptrack.JumpTrack(address="test-device")
            device.send_command=AsyncMock()
            self.assertIsNone(await device.prepareSendFreeFallSoundSetupCommand(0,1))
            device.send_command.assert_not_awaited()

    async def test_original_destructive_gate(self):
        with patch.object(jumptrack,'BleakClient') as ble:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                await jumptrack.main(['java','prepareEraseEntireLogbookCommand'])
            ble.assert_not_called()

    async def test_all_constants_offline(self):
        with patch.object(jumptrack,'BleakClient') as ble:
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                await jumptrack.main(['constants'])
            self.assertEqual(json.loads(output.getvalue()),master.CONSTANTS)
            ble.assert_not_called()
        self.assertIsInstance(UARTCommandBuilder.INSTANCE,UARTCommandBuilder)
        self.assertEqual(UARTCommandBuilder.Companion().prepareGetDeviceInfoCommand(),'Who?')

    async def test_json_errors_fail_before_bluetooth(self):
        invalid=[['java','prepareSetTotalFreeFallTimeCommand','[1,"2",3]'],
                 ['java','prepareSetSpeedUOM','["FEET_SECONDS"]'],
                 ['java','prepareSendAltitudeCommand','[9223372036854775808,0]'],
                 ['java','prepareGetDeviceInfoCommand','['],
                 ['java','prepareGetDeviceInfoCommand','{}'],
                 ['java','prepareSendFlightWarningsCommand','[[1,2,3]]']]
        with patch.object(jumptrack,'BleakClient') as ble:
            for args in invalid:
                with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    await jumptrack.main(args)
            ble.assert_not_called()

    def test_friendly_cli_has_master_widths_and_sign(self):
        examples={
            'profile 1000000':'Get Hex Profile in Jump 1000000',
            'acc -1 1000 -2':'Get Hex xACC -0001 1000 -02',
            'motion-alarm -1 1000':'Enable Motion -01 1000',
            'backlight on --value 100':'Backlight On 100',
            'set-warnings flight 1 2 3 4 5':'W-01-00000-00001-00002-00003',
            'set-altitude 123 --sign -2':'W-17-00000-00000-00001-00123',
        }
        import shlex
        for cli, expected in examples.items():
            with self.subTest(cli=cli):
                self.assertEqual(preview(operation(self.parser.parse_args(shlex.split(cli))),UARTCommandBuilder()),expected)


if __name__ == '__main__':
    unittest.main()
