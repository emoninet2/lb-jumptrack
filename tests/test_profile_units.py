"""Conversion assumptions and units, independent of the unverified wire encoding."""
import contextlib
import io
import math
import unittest
from plot_profile import convert_profile, main


class ProfileUnitsTests(unittest.TestCase):
    def test_reference_height_units_and_raw_preservation(self):
        profile={'raw_words':[6000,8000,10000]}
        meters=convert_profile(profile,pressure_scale_hpa=0.1,reference_pressure_hpa=1000)
        feet=convert_profile(profile,pressure_scale_hpa=0.1,reference_pressure_hpa=1000,altitude_unit='feet')
        self.assertEqual(meters['pressure_hpa'],[600,800,1000])
        self.assertAlmostEqual(meters['estimated_height'][-1],0)
        self.assertGreater(meters['estimated_height'][0],meters['estimated_height'][1])
        self.assertAlmostEqual(feet['estimated_height'][0]*0.3048,meters['estimated_height'][0])
        self.assertEqual(profile['raw_words'],[6000,8000,10000])

    def test_inverse_of_published_pressure_curve(self):
        # NASA forward curve, independently written: T=15.04-.00649*h,
        # p[kPa]=101.29*((T+273.1)/288.08)**5.256.
        def pressure_hpa(height):
            temperature=15.04-0.00649*height
            return 10*101.29*((temperature+273.1)/288.08)**5.256
        reference=pressure_hpa(0)
        words=[pressure_hpa(1000),pressure_hpa(500),reference]
        result=convert_profile({'raw_words':words},pressure_scale_hpa=1,reference_pressure_hpa=reference)
        for actual,expected in zip(result['estimated_height_m'],[1000,500,0]):
            self.assertAlmostEqual(actual,expected,places=8)

    def test_invalid_conversion_parameters(self):
        for scale,reference in [(0,1000),(-1,1000),(math.nan,1000),(1,math.inf),(True,1000)]:
            with self.subTest(scale=scale,reference=reference),self.assertRaises(ValueError):
                convert_profile({'raw_words':[6000]},pressure_scale_hpa=scale,reference_pressure_hpa=reference)
        with self.assertRaises(ValueError):
            convert_profile({'raw_words':[0]},pressure_scale_hpa=0.1,reference_pressure_hpa=1000)

    def test_units_require_explicit_assumptions_before_reading(self):
        for args in [['--file','nonexistent','--units','feet'],['--file','nonexistent','--pressure-scale','0.1']]:
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exc:
                main(args)
            self.assertEqual(exc.exception.code,2)


if __name__ == '__main__':
    unittest.main()
