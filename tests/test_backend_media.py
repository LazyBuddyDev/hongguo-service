"""Boundary checks for the MP4 parser used by the progressive path."""
import unittest
from lazybuddy_hongguo.backend import media_container as m


class Tests(unittest.TestCase):
    def test_boxes_respect_a_parent_boundary(self):
        with self.assertRaises(ValueError):
            list(m.boxes(b'\x00\x00\x00\x0cmoov',0,8))
        with self.assertRaises(ValueError):
            m.uint(b'12345678',6,4,8)

    def test_range_bounds(self):
        for value,expected in [(None,(0,9)),('bytes=2-4',(2,4)),('bytes=8-',(8,9)),('bytes=-3',(7,9)),('bytes=8-99',(8,9))]:
            self.assertEqual(m.byte_range(value,10),expected)
        for value in ('bytes=10-','bytes=3-2','bytes=0-1,3-4','bytes=-0','bytes=bad','other=0-1'):
            with self.assertRaises(ValueError):m.byte_range(value,10)


if __name__=="__main__":unittest.main()
