import unittest
import numpy as np
from src.multivector import matrix, pack, unpack, score


class MultiVectorTests(unittest.TestCase):
    def test_packed_round_trip_and_late_interaction(self):
        query = [[1., 0.], [0., 1.]]
        document = [[1., 0.], [0., 1.], [-1., 0.]]
        tokens, dimensions, data = pack(document)
        self.assertEqual(len(data), 3 * 2 * 2)
        self.assertAlmostEqual(score(query, unpack(data, tokens, dimensions)), 2.)
        self.assertLess(score(query, [[1., 0.]]), 2.)

    def test_scoring_is_bounded_across_token_blocks(self):
        document = np.tile([[1., 0.]], (700, 1))
        document[-1] = [0., 1.]
        self.assertAlmostEqual(score([[1., 0.], [0., 1.]], document), 2.)

    def test_invalid_vectors_and_shapes_are_rejected(self):
        for value in [[], [[0., 0.]], [[float('nan'), 1.]], [[[1.]]]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pack(value)
        with self.assertRaises(ValueError):
            unpack(b'bad', 2, 2)
        with self.assertRaises(ValueError):
            score([[1., 0.]], [[1., 0., 0.]])
