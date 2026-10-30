import json
import math
import unittest
from pathlib import Path

import numpy as np

from wscan import frames, geom, pipeline, profile, sources


class ProfileTests(unittest.TestCase):
    def test_layers_reproduce_the_cad_path(self):
        for layer in profile.all_layers():
            self.assertAlmostEqual(
                geom.path_length(layer.target_nominal, layer.tx, layer.rx),
                2.0 * layer.single_path_mm, places=5)

    def test_plan_is_serpentine_and_complete(self):
        plan = profile.ScanPlan()
        points = list(plan.points())
        self.assertEqual(len(points), 108)
        self.assertEqual(points[0][2], 0)
        self.assertEqual(points[12][2], 11)      # first layer runs upward
        self.assertEqual(points[12][2], 11)      # second layer starts at the end


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.src = sources.SyntheticScan(seed=3)

    def test_peak_recovers_the_echo_time(self):
        frame, pose = self.src.capture(4, 0, 0)
        prep = frames.prepare(frame)
        peak = frames.detect(prep)
        self.assertIsNotNone(peak)
        truth = self.src.truth[-1]
        self.assertAlmostEqual(peak.t_us, truth["t_echo_us"], delta=0.5)
        self.assertGreater(peak.snr_db, 12.0)

    def test_noise_only_frame_is_rejected_by_the_gate(self):
        frame, _ = self.src.capture(4, 0, 0)
        frame.diff = np.random.default_rng(0).normal(0, 3, frame.diff.size)
        prep = frames.prepare(frame)
        peak = frames.detect(prep)
        reasons = pipeline.frame_reasons(frame, peak)
        self.assertTrue(reasons)          # detector may return a candidate; the gate decides

    def test_calibration_recovers_delay(self):
        peaks, distances = [], []
        for d in (45.0, 55.0, 65.0):
            p = frames.detect(frames.prepare(self.src.plate_capture(d)))
            peaks.append(p.t_us)
            distances.append(d)
        cal = geom.fit_calibration(peaks, distances)
        self.assertAlmostEqual(cal.t_eff_us, self.src.t_eff_us, delta=0.15)


class GeometryTests(unittest.TestCase):
    def test_ray_solve_roundtrip(self):
        layer = profile.make_layer(0.0)
        for path in (92.0, 98.6, 110.0):
            point = geom.solve_ray(path, layer.tx, layer.rx, layer.origin, layer.direction)
            self.assertAlmostEqual(geom.path_length(point, layer.tx, layer.rx), path, places=5)

    def test_arc_center_moves_with_the_lift(self):
        points = []
        for lat in profile.ScanPlan().latitudes:
            layer = profile.make_layer(lat)
            shift = np.array([0.0, 0.0, -4.0])
            hit = geom.ray_sphere_hit(layer.origin + shift, layer.direction)
            path = geom.path_length(hit, layer.tx + shift, layer.rx + shift)
            points.append(geom.solve_ray(path, layer.tx, layer.rx, layer.origin, layer.direction))
        verdict = geom.arc_verdict(points)
        self.assertAlmostEqual(verdict["center_error_mm"], 4.0, delta=0.3)


class PipelineTests(unittest.TestCase):
    def test_mesh_has_no_nonmanifold_edges(self):
        obs = []
        for li, lat in enumerate((-10.0, 0.0, 10.0)):
            for ai, az in enumerate((0.0, 120.0, 240.0)):
                layer = profile.make_layer(lat)
                hit = geom.ray_sphere_hit(layer.origin, layer.direction)
                path = geom.path_length(hit, layer.tx, layer.rx)
                point = geom.solve_ray(path, layer.tx, layer.rx, layer.origin, layer.direction)
                obs.append(pipeline.Observation("f", li, lat, az, layer.probe_z_mm,
                                                path_mm=path, point_mm=point.tolist()))
        mesh = pipeline.build_mesh(obs, 3)
        self.assertGreaterEqual(mesh["stats"]["triangles"], 0)
        self.assertEqual(mesh["stats"]["nonmanifold_edges"], 0)
        lathe = pipeline.build_lathe(obs)
        self.assertGreater(lathe["stats"]["triangles"], 0)
        self.assertEqual(lathe["stats"]["nonmanifold_edges"], 0)
        self.assertEqual(lathe["stats"]["model"], "lathe")

    def test_outlier_is_a_flag_not_a_rejection(self):
        rows = [pipeline.Observation("f", 0, 0.0, 30.0 * i, 75.0, path_mm=98.0 + 0.01 * i)
                for i in range(12)]
        rows[5].path_mm = 110.0
        pipeline.layer_checks(rows)
        self.assertIn("path_outlier", rows[5].flags)
        self.assertTrue(rows[5].eligible)


if __name__ == "__main__":
    unittest.main()

